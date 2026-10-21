from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header

from app_base.core.errors import ApiError
from app_base.core.security import FreeIDTokenVerifier


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    role: str | None = None
    claims: dict | None = None


@dataclass(frozen=True)
class AuthenticatedService:
    subject: str
    client_id: str | None = None
    scopes: frozenset[str] = frozenset()
    claims: dict | None = None


@dataclass(frozen=True)
class DelegatedOperator:
    service: AuthenticatedService
    operator_user_id: UUID
    reason: str
    request_id: str


async def require_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> AuthenticatedUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "TOKEN_MISSING", "Authentication is required.")
    token = authorization.removeprefix("Bearer ").strip()
    claims = FreeIDTokenVerifier(require_audience=False).verify(token)
    if claims.token_type == "service" or claims.subject.startswith("service:"):
        raise ApiError(403, "USER_TOKEN_REQUIRED", "A user token is required.")
    try:
        user_id = UUID(claims.subject)
    except ValueError as exc:
        raise ApiError(401, "TOKEN_INVALID", "Token subject is not a valid user id.") from exc
    return AuthenticatedUser(user_id=user_id, role=claims.role, claims=claims.claims)


def require_service_token(
    *,
    required_scope: str | None = None,
    expected_subject: str | None = None,
) -> Callable[[str | None], AuthenticatedService]:
    async def dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_client_id: str | None = Header(default=None, alias="X-Client-ID"),
    ) -> AuthenticatedService:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "TOKEN_MISSING", "Authentication is required.")
        token = authorization.removeprefix("Bearer ").strip()
        claims = FreeIDTokenVerifier().verify(token)
        if claims.token_type != "service" or not claims.subject.startswith("service:"):
            raise ApiError(403, "SERVICE_TOKEN_REQUIRED", "A service token is required.")
        if expected_subject and claims.subject != expected_subject:
            raise ApiError(403, "SERVICE_SUBJECT_FORBIDDEN", "Service subject is not allowed.")

        token_client_id = claims.claims.get("client_id")
        if x_client_id is None:
            raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID is required.")
        if token_client_id != x_client_id:
            raise ApiError(401, "SERVICE_CLIENT_ID_INVALID", "X-Client-ID must match the service token client_id.")

        raw_scope = str(claims.claims.get("scope", ""))
        scopes = frozenset(scope for scope in raw_scope.split() if scope)
        if required_scope and required_scope not in scopes:
            raise ApiError(403, "SERVICE_SCOPE_FORBIDDEN", "Service token is missing the required scope.")
        return AuthenticatedService(
            subject=claims.subject,
            client_id=str(token_client_id) if token_client_id else None,
            scopes=scopes,
            claims=claims.claims,
        )

    return dependency


def require_delegated_operator(*, required_scope: str) -> Callable[..., DelegatedOperator]:
    service_dependency = require_service_token(
        required_scope=required_scope,
        expected_subject="service:diddiadmin",
    )

    async def dependency(
        service: AuthenticatedService = Depends(service_dependency),
        x_backoffice_actor: str | None = Header(default=None, alias="X-Backoffice-Actor"),
        x_backoffice_reason: str | None = Header(default=None, alias="X-Backoffice-Reason"),
        x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> DelegatedOperator:
        if not x_backoffice_actor:
            raise ApiError(403, "BACKOFFICE_ACTOR_REQUIRED", "A delegated operator is required.")
        try:
            operator_user_id = UUID(x_backoffice_actor)
        except ValueError as exc:
            raise ApiError(403, "BACKOFFICE_ACTOR_INVALID", "The delegated operator is invalid.") from exc
        reason = (x_backoffice_reason or "").strip()
        if not reason or len(reason) > 200:
            raise ApiError(403, "BACKOFFICE_REASON_REQUIRED", "A valid Backoffice reason is required.")
        if not x_request_id:
            raise ApiError(400, "REQUEST_ID_REQUIRED", "X-Request-ID is required.")
        try:
            request_id = str(UUID(x_request_id))
        except ValueError as exc:
            raise ApiError(400, "REQUEST_ID_INVALID", "X-Request-ID must be a UUID.") from exc
        return DelegatedOperator(
            service=service,
            operator_user_id=operator_user_id,
            reason=reason,
            request_id=request_id,
        )

    return dependency
