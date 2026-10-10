from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Header

from app_base.core.errors import ApiError
from app_base.core.security import FreeIDTokenVerifier


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    role: str | None = None
    claims: dict | None = None


async def require_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthenticatedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "TOKEN_MISSING", "Authentication is required.")
    token = authorization.removeprefix("Bearer ").strip()
    claims = FreeIDTokenVerifier().verify(token)
    if claims.token_type == "service" or claims.subject.startswith("service:"):
        raise ApiError(403, "USER_TOKEN_REQUIRED", "A user token is required.")
    try:
        user_id = UUID(claims.subject)
    except ValueError as exc:
        raise ApiError(401, "TOKEN_INVALID", "Token subject is not a valid user id.") from exc
    return AuthenticatedUser(user_id=user_id, role=claims.role, claims=claims.claims)
