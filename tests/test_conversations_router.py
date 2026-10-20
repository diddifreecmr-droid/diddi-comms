from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app_base.core.auth_deps import AuthenticatedUser, require_current_user
from app_base.core.database import get_session
from app_base.main import app

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
MESSAGE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def conversations_client(monkeypatch):
    async def fake_user():
        return AuthenticatedUser(user_id=PASSENGER_ID)

    async def fake_session():
        return object()

    async def fake_ensure(self, *, task, actor_user_id, request_id=None, idempotency_key=None):
        assert task.owner_service == "diddigo"
        assert task.task_type == "ride"
        assert task.task_id == TASK_ID
        assert actor_user_id == PASSENGER_ID
        assert idempotency_key == "idem-1"
        return SimpleNamespace(
            created=True,
            conversation=SimpleNamespace(
                id=CONVERSATION_ID,
                conversation_type="task",
                owner_service="diddigo",
                task_type="ride",
                task_id=TASK_ID,
                state="active",
                task_version=1791633600,
                closes_at=None,
            ),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.EnsureTaskConversationService.ensure",
        fake_ensure,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)


def test_ensure_task_conversation_route_returns_conversation(conversations_client) -> None:
    response = conversations_client.post(
        f"/comms/v1/tasks/diddigo/ride/{TASK_ID}/conversation",
        headers={"Idempotency-Key": "idem-1"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(CONVERSATION_ID),
        "type": "task",
        "owner_service": "diddigo",
        "task_type": "ride",
        "task_id": str(TASK_ID),
        "state": "active",
        "task_version": 1791633600,
        "closes_at": None,
        "created": True,
    }


def test_ensure_task_conversation_requires_user_token() -> None:
    response = TestClient(app).post(f"/comms/v1/tasks/diddigo/ride/{TASK_ID}/conversation")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_MISSING"


@pytest.fixture
def send_message_client(monkeypatch):
    async def fake_user():
        return AuthenticatedUser(user_id=PASSENGER_ID)

    async def fake_session():
        return object()

    async def fake_send(
        self,
        *,
        conversation_id,
        actor_user_id,
        client_message_id,
        body,
        request_id=None,
        idempotency_key=None,
    ):
        assert conversation_id == CONVERSATION_ID
        assert actor_user_id == PASSENGER_ID
        assert client_message_id == "client-1"
        assert body == "Hello"
        return SimpleNamespace(
            created=True,
            message=SimpleNamespace(
                id=MESSAGE_ID,
                conversation_id=CONVERSATION_ID,
                sequence=1,
                sender_user_id=PASSENGER_ID,
                client_message_id="client-1",
                body="Hello",
                moderation_status="accepted",
            ),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SendMessageService.send",
        fake_send,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)


def test_send_message_route_returns_message(send_message_client) -> None:
    response = send_message_client.post(
        f"/comms/v1/conversations/{CONVERSATION_ID}/messages",
        json={"client_message_id": "client-1", "body": "Hello"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(MESSAGE_ID),
        "conversation_id": str(CONVERSATION_ID),
        "sequence": 1,
        "sender_user_id": str(PASSENGER_ID),
        "client_message_id": "client-1",
        "body": "Hello",
        "moderation_status": "accepted",
        "delivery_status": "pending",
        "created": True,
    }


@pytest.fixture
def read_cursor_client(monkeypatch):
    async def fake_user():
        return AuthenticatedUser(user_id=PASSENGER_ID)

    async def fake_session():
        return object()

    async def fake_authorization(*args, **kwargs):
        return None

    async def fake_mark(self, *, conversation_id, actor_user_id, read_sequence, request_id=None):
        assert conversation_id == CONVERSATION_ID
        assert actor_user_id == PASSENGER_ID
        assert read_sequence == 7
        return SimpleNamespace(conversation_id=CONVERSATION_ID, read_sequence=7)

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router._ensure_user_can_read_conversation",
        fake_authorization,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.MarkConversationReadService.mark",
        fake_mark,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)


def test_mark_conversation_read_route_returns_cursor(read_cursor_client) -> None:
    response = read_cursor_client.post(
        f"/comms/v1/conversations/{CONVERSATION_ID}/read",
        json={"read_seq": 7},
    )

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": str(CONVERSATION_ID),
        "read_seq": 7,
    }
