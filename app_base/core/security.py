from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import Header
from jwt import PyJWKClient

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
    def __init__(self, jwks_url: str | None = None, issuer: str | None = None, audience: str | None = None) -> None:
        self.jwks_url = jwks_url or settings.identity_jwks_url
        self.issuer = issuer or settings.identity_issuer
        self.audience = audience or settings.identity_audience

    def verify(self, token: str) -> TokenClaims:
        if not self.jwks_url:
            raise ApiError(503, "IDENTITY_JWKS_NOT_CONFIGURED", "Identity JWKS URL is not configured.")
        signing_key = PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["sub", "exp", "iat"]},
        )
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

