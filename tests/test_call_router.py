from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from app_base.core.auth_deps import AuthenticatedUser, require_current_user
from app_base.core.database import get_session
from app_base.main import app

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
ACTOR_ID = UUID("22222222-2222-2222-2222-222222222222")
TARGET_ID = UUID("33333333-3333-3333-3333-333333333333")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def test_call_attempt_returns_safe_tel_action(monkeypatch) -> None:
    async def fake_user():
        return AuthenticatedUser(user_id=ACTOR_ID)

    async def fake_session():
        return object()

    async def fake_create(self, **kwargs):
        assert kwargs["target_user_id"] == TARGET_ID
        return SimpleNamespace(
            created=True,
            target_phone_e164="+237600000002",
            attempt=SimpleNamespace(
                id=ATTEMPT_ID,
                conversation_id=CONVERSATION_ID,
                target_user_id=TARGET_ID,
                outcome="authorized",
            ),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.CreateCallAttemptService.create", fake_create
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        response = TestClient(app).post(
            f"/comms/v1/conversations/{CONVERSATION_ID}/call-attempts",
            headers={"Idempotency-Key": "call-1"},
            json={"target_user_id": str(TARGET_ID)},
        )
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json()["dial_action"] == {"scheme": "tel", "value": "tel:+237600000002"}
