from __future__ import annotations

from uuid import UUID

import pytest

from app_base.core.auth_deps import (
    AuthenticatedService,
    require_current_user,
    require_delegated_operator,
    require_service_token,
)
from app_base.core.errors import ApiError
from app_base.core.security import TokenClaims

USER_ID = UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.asyncio
async def test_current_user_accepts_freeid_user_token_without_audience(monkeypatch) -> None:
    captured = {}

    def fake_verify(self, token: str) -> TokenClaims:
        captured["require_audience"] = self.require_audience
        assert token == "user-token"
        return TokenClaims(
            subject=str(USER_ID),
            token_type="user",
            role="user",
            status="active",
            claims={"sub": str(USER_ID), "status": "active"},
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)

    user = await require_current_user(authorization="Bearer user-token")

    assert user.user_id == USER_ID
    assert captured["require_audience"] is False


@pytest.mark.asyncio
async def test_service_token_still_requires_audience(monkeypatch) -> None:
    captured = {}

    def fake_verify(self, token: str) -> TokenClaims:
        captured["require_audience"] = self.require_audience
        assert token == "service-token"
        return TokenClaims(
            subject="service:backoffice",
            token_type="service",
            role="service",
            status="active",
            claims={
                "client_id": "backoffice-staging-diddicomms",
                "scope": "diddicomms:support-cases:read",
            },
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    dependency = require_service_token(required_scope="diddicomms:support-cases:read")

    service = await dependency(
        authorization="Bearer service-token",
        x_client_id="backoffice-staging-diddicomms",
    )

    assert service.subject == "service:backoffice"
    assert captured["require_audience"] is True


@pytest.mark.asyncio
async def test_service_token_rejects_missing_scope(monkeypatch) -> None:
    def fake_verify(self, token: str) -> TokenClaims:
        return TokenClaims(
            subject="service:backoffice",
            token_type="service",
            role="service",
            status="active",
            claims={"client_id": "backoffice-staging-diddicomms", "scope": ""},
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    dependency = require_service_token(required_scope="diddicomms:support-cases:read")

    with pytest.raises(ApiError) as exc:
        await dependency(
            authorization="Bearer service-token",
            x_client_id="backoffice-staging-diddicomms",
        )

    assert exc.value.code == "SERVICE_SCOPE_FORBIDDEN"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("token_type", "subject"),
    [
        ("user", "service:diddiadmin"),
        ("service", str(USER_ID)),
    ],
)
async def test_service_token_requires_both_service_type_and_subject(monkeypatch, token_type, subject) -> None:
    def fake_verify(self, token: str) -> TokenClaims:
        return TokenClaims(
            subject=subject,
            token_type=token_type,
            role="service",
            status="active",
            claims={"client_id": "diddiadmin-comms", "scope": "diddicomms:backoffice:read"},
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    dependency = require_service_token(required_scope="diddicomms:backoffice:read")

    with pytest.raises(ApiError) as exc:
        await dependency(authorization="Bearer confused-token", x_client_id="diddiadmin-comms")

    assert exc.value.code == "SERVICE_TOKEN_REQUIRED"


@pytest.mark.asyncio
async def test_service_token_rejects_header_client_id_mismatch(monkeypatch) -> None:
    def fake_verify(self, token: str) -> TokenClaims:
        return TokenClaims(
            subject="service:diddiadmin",
            token_type="service",
            role="service",
            status="active",
            claims={"client_id": "signed-client", "scope": "diddicomms:backoffice:read"},
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    dependency = require_service_token(required_scope="diddicomms:backoffice:read")

    with pytest.raises(ApiError) as exc:
        await dependency(authorization="Bearer service-token", x_client_id="spoofed-client")

    assert exc.value.code == "SERVICE_CLIENT_ID_INVALID"


@pytest.mark.asyncio
async def test_delegated_operator_requires_uuid_request_id() -> None:
    dependency = require_delegated_operator(required_scope="diddicomms:backoffice:read")
    service = AuthenticatedService(
        subject="service:diddiadmin",
        client_id="diddiadmin-comms",
        scopes=frozenset({"diddicomms:backoffice:read"}),
    )

    with pytest.raises(ApiError) as exc:
        await dependency(
            service=service,
            x_backoffice_actor=str(USER_ID),
            x_backoffice_reason="support-case:42",
            x_request_id="not-a-uuid",
        )

    assert exc.value.code == "REQUEST_ID_INVALID"
