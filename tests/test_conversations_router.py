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
        "delivery_status": "accepted",
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


def test_send_message_does_not_reveal_private_conversation_existence(send_message_client, monkeypatch) -> None:
    async def denied(self, **kwargs):
        raise PermissionError("ACTOR_NOT_TASK_PARTICIPANT")

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SendMessageService.send",
        denied,
    )
    denied_response = send_message_client.post(
        f"/comms/v1/conversations/{CONVERSATION_ID}/messages",
        json={"client_message_id": "client-1", "body": "Hello"},
    )

    async def missing(self, **kwargs):
        raise LookupError("CONVERSATION_NOT_FOUND")

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SendMessageService.send",
        missing,
    )
    missing_response = send_message_client.post(
        f"/comms/v1/conversations/{CONVERSATION_ID}/messages",
        json={"client_message_id": "client-1", "body": "Hello"},
    )

    assert denied_response.status_code == missing_response.status_code == 404
    assert denied_response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
    assert missing_response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_recipient_can_acknowledge_message_delivery(monkeypatch) -> None:
    async def fake_user():
        return AuthenticatedUser(user_id=PASSENGER_ID)

    async def fake_session():
        return object()

    async def fake_acknowledge(
        self,
        *,
        conversation_id,
        message_id,
        recipient_user_id,
        status,
        request_id=None,
    ):
        assert recipient_user_id == PASSENGER_ID
        assert status == "read"
        return SimpleNamespace(
            conversation_id=conversation_id,
            message_id=message_id,
            status="read",
            changed=True,
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.MessageDeliveryService.acknowledge",
        fake_acknowledge,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        response = TestClient(app).post(
            f"/comms/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/delivery",
            json={"status": "read"},
        )
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json() == {
        "conversation_id": str(CONVERSATION_ID),
        "message_id": str(MESSAGE_ID),
        "status": "read",
        "changed": True,
    }


def test_user_can_mute_and_report_without_exposing_report_details(monkeypatch) -> None:
    report_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    async def fake_user():
        return AuthenticatedUser(user_id=PASSENGER_ID)

    async def fake_session():
        return object()

    async def fake_mute(self, *, conversation_id, user_id, muted, request_id=None):
        return SimpleNamespace(muted=muted)

    async def fake_report(
        self,
        *,
        conversation_id,
        message_id,
        reporter_user_id,
        category,
        details,
        idempotency_key,
        request_id=None,
    ):
        assert details == "Private report details"
        return SimpleNamespace(
            created=True,
            report=SimpleNamespace(
                id=report_id,
                conversation_id=conversation_id,
                message_id=message_id,
                category=category,
                status="open",
            ),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.ConversationSafetyService.set_muted",
        fake_mute,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.ConversationSafetyService.report_message",
        fake_report,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        client = TestClient(app)
        mute_response = client.put(
            f"/comms/v1/conversations/{CONVERSATION_ID}/mute",
            json={"muted": True},
        )
        report_response = client.post(
            f"/comms/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/reports",
            headers={"Idempotency-Key": "report-1"},
            json={"category": "unsafe", "details": "Private report details"},
        )
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)

    assert mute_response.json() == {"conversation_id": str(CONVERSATION_ID), "muted": True}
    assert report_response.status_code == 200
    assert report_response.json()["report_id"] == str(report_id)
    assert "details" not in report_response.json()
