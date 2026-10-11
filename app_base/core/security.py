from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header
from jwt import PyJWKClient, PyJWTError

from app_base.core.errors import ApiError
from app_base.core.settings import settings


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    token_type: str
    role: str | None
    status: str | None
    claims: dict[str, Any]


def require_metrics_token(authorization: str | None = Header(default=None, alias="Authorization")) -> None:
    expected = f"Bearer {settings.metrics_bearer_token}"
    if authorization != expected:
        raise ApiError(403, "METRICS_FORBIDDEN", "Metrics access is forbidden.")


class FreeIDTokenVerifier:
    def __init__(
        self,
        jwks_url: str | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        require_audience: bool = True,
    ) -> None:
        self.jwks_url = jwks_url or settings.identity_jwks_url
        self.issuer = issuer or settings.identity_issuer
        self.audience = audience or settings.identity_audience
        self.require_audience = require_audience

    def verify(self, token: str) -> TokenClaims:
        if not self.jwks_url:
            raise ApiError(503, "IDENTITY_JWKS_NOT_CONFIGURED", "Identity JWKS URL is not configured.")
        try:
            signing_key = PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token)
            decode_kwargs = {
                "key": signing_key.key,
                "algorithms": ["RS256"],
                "issuer": self.issuer,
                "options": {"require": ["sub", "exp", "iat"]},
            }
            if self.require_audience:
                decode_kwargs["audience"] = self.audience
            else:
                decode_kwargs["options"]["verify_aud"] = False
            claims = jwt.decode(token, **decode_kwargs)
        except PyJWTError as exc:
            raise ApiError(401, "TOKEN_INVALID", "Token is invalid.") from exc
        status = claims.get("status")
        if status != "active":
            raise ApiError(403, "IDENTITY_NOT_ACTIVE", "Identity is not active.")
        return TokenClaims(
            subject=str(claims["sub"]),
            token_type=str(claims.get("token_type", "user")),
            role=claims.get("role"),
            status=status,
            claims=claims,
        )
