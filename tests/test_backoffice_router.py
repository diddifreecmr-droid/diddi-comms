from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app_base.core.database import get_session
from app_base.core.security import TokenClaims
from app_base.main import app

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
OPERATOR_ID = UUID("33333333-3333-3333-3333-333333333333")
TARGET_ID = UUID("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
REQUEST_ID = UUID("44444444-4444-4444-4444-444444444444")


@pytest.fixture
def backoffice_client(monkeypatch):
    async def fake_session():
        return object()

    def fake_verify(self, token):
        return TokenClaims(
            subject="service:diddiadmin",
            token_type="service",
            role="service",
            status="active",
            claims={
                "client_id": "diddiadmin-comms",
                "scope": "diddicomms:backoffice:read diddicomms:backoffice:write",
            },
        )

    async def fake_ensure(self, *, task, operator, idempotency_key):
        assert task.task_id == TASK_ID
        assert operator.operator_user_id == OPERATOR_ID
        assert operator.reason == "support-case:42"
        assert idempotency_key == "ensure-1"
        return SimpleNamespace(
            created=False,
            conversation=SimpleNamespace(
                id=CONVERSATION_ID,
                conversation_type="task",
                owner_service="diddigo",
                task_type="ride",
                task_id=TASK_ID,
                state="active",
                task_version=7,
                closes_at=None,
            ),
        )

    async def fake_list(self, *, conversation_id, operator, after_sequence, limit):
        assert conversation_id == CONVERSATION_ID
        assert operator.service.subject == "service:diddiadmin"
        return [_message()]

    async def fake_send(
        self,
        *,
        conversation_id,
        operator,
        client_message_id,
        body,
        idempotency_key,
    ):
        assert conversation_id == CONVERSATION_ID
        assert operator.operator_user_id == OPERATOR_ID
        assert idempotency_key == "message-1"
        assert body == "Operational update"
        return SimpleNamespace(message=_message(), created=True)

    async def fake_statuses(self, message_ids):
        return {MESSAGE_ID: "delivered"}

    async def fake_call(self, *, conversation_id, actor_user_id, target_user_id, idempotency_key, request_id, allow_delegated_operator, actor_service):
        assert conversation_id == CONVERSATION_ID
        assert actor_user_id == OPERATOR_ID
        assert target_user_id == TARGET_ID
        assert idempotency_key == "call-1"
        assert allow_delegated_operator is True
        assert actor_service == "service:diddiadmin"
        return SimpleNamespace(
            created=True,
            target_phone_e164="+237600000000",
            attempt=SimpleNamespace(
                id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                conversation_id=CONVERSATION_ID,
                target_user_id=TARGET_ID,
                outcome="authorized",
            ),
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.BackofficeConversationService.ensure_conversation",
        fake_ensure,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.BackofficeConversationService.list_messages",
        fake_list,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.BackofficeConversationService.send_message",
        fake_send,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.MessageDeliveryRepository.statuses_for_messages",
        fake_statuses,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.CreateCallAttemptService.create",
        fake_call,
    )
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_backoffice_can_ensure_read_and_write_task_chat(backoffice_client) -> None:
    headers = _headers()
    response = backoffice_client.post(
        f"/comms/v1/backoffice/tasks/diddigo/ride/{TASK_ID}/conversation",
        headers={**headers, "Idempotency-Key": "ensure-1"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == str(CONVERSATION_ID)

    response = backoffice_client.get(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(MESSAGE_ID)

    response = backoffice_client.post(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers={**headers, "Idempotency-Key": "message-1"},
        json={"client_message_id": "agent-message-1", "body": "Operational update"},
    )
    assert response.status_code == 200
    assert response.json()["sender_user_id"] == str(OPERATOR_ID)


def test_backoffice_rejects_missing_delegated_actor(backoffice_client) -> None:
    headers = _headers()
    headers.pop("X-Backoffice-Actor")
    response = backoffice_client.get(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "BACKOFFICE_ACTOR_REQUIRED"


def test_backoffice_can_create_audited_call_attempt(backoffice_client) -> None:
    response = backoffice_client.post(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/call-attempts",
        headers={**_headers(), "Idempotency-Key": "call-1"},
        json={"target_user_id": str(TARGET_ID)},
    )
    assert response.status_code == 200
    assert response.json()["dial_action"] == {"scheme": "tel", "value": "tel:+237600000000"}


def test_backoffice_rejects_missing_idempotency_key(backoffice_client) -> None:
    response = backoffice_client.post(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=_headers(),
        json={"client_message_id": "agent-message-1", "body": "Operational update"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.parametrize(
    ("claims", "expected_code"),
    [
        (
            {
                "sub": "service:not-admin",
                "token_type": "service",
                "client_id": "diddiadmin-comms",
                "scope": "diddicomms:backoffice:read",
            },
            "SERVICE_SUBJECT_FORBIDDEN",
        ),
        (
            {
                "sub": "service:diddiadmin",
                "token_type": "service",
                "client_id": "diddiadmin-comms",
                "scope": "diddicomms:backoffice:write",
            },
            "SERVICE_SCOPE_FORBIDDEN",
        ),
        (
            {
                "sub": "service:diddiadmin",
                "token_type": "user",
                "client_id": "diddiadmin-comms",
                "scope": "diddicomms:backoffice:read",
            },
            "SERVICE_TOKEN_REQUIRED",
        ),
    ],
)
def test_backoffice_rejects_token_confusion(backoffice_client, monkeypatch, claims, expected_code) -> None:
    def fake_verify(self, token):
        return TokenClaims(
            subject=claims["sub"],
            token_type=claims["token_type"],
            role="service",
            status="active",
            claims=claims,
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)

    response = backoffice_client.get(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=_headers(),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == expected_code


def test_backoffice_rejects_spoofed_client_id(backoffice_client) -> None:
    headers = _headers()
    headers["X-Client-ID"] = "spoofed-client"

    response = backoffice_client.get(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SERVICE_CLIENT_ID_INVALID"


@pytest.mark.parametrize(
    ("header", "value", "expected_code", "status_code"),
    [
        ("X-Backoffice-Actor", "not-a-uuid", "BACKOFFICE_ACTOR_INVALID", 403),
        ("X-Backoffice-Reason", "", "BACKOFFICE_REASON_REQUIRED", 403),
        ("X-Request-ID", "not-a-uuid", "REQUEST_ID_INVALID", 400),
    ],
)
def test_backoffice_rejects_invalid_delegation_context(
    backoffice_client,
    header,
    value,
    expected_code,
    status_code,
) -> None:
    headers = _headers()
    headers[header] = value

    response = backoffice_client.get(
        f"/comms/v1/backoffice/conversations/{CONVERSATION_ID}/messages",
        headers=headers,
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == expected_code


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer service-token",
        "X-Client-ID": "diddiadmin-comms",
        "X-Request-ID": str(REQUEST_ID),
        "X-Backoffice-Actor": str(OPERATOR_ID),
        "X-Backoffice-Reason": "support-case:42",
    }


def _message():
    return SimpleNamespace(
        id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        sequence=2,
        sender_user_id=OPERATOR_ID,
        client_message_id="agent-message-1",
        body="Operational update",
        moderation_status="accepted",
    )
