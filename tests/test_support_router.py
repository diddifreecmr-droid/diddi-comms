from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app_base.core.auth_deps import AuthenticatedUser, require_current_user
from app_base.core.database import get_session
from app_base.core.security import TokenClaims
from app_base.main import app

CASE_ID = UUID("aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")
CONVERSATION_ID = UUID("bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb")
REQUESTER_ID = UUID("22222222-2222-2222-2222-222222222222")
AGENT_ID = UUID("33333333-3333-3333-3333-333333333333")
TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
MESSAGE_ID = UUID("cccccccc-3333-3333-3333-cccccccccccc")


@pytest.fixture
def support_user_client(monkeypatch):
    async def fake_user():
        return AuthenticatedUser(user_id=REQUESTER_ID)

    async def fake_session():
        return object()

    async def fake_open_case(
        self,
        *,
        requester_user_id,
        subject,
        priority="normal",
        initial_message=None,
        task=None,
        request_id=None,
        idempotency_key=None,
    ):
        assert requester_user_id == REQUESTER_ID
        assert subject == "Ride problem"
        assert priority == "high"
        assert initial_message == "The driver is not moving"
        assert task.owner_service == "diddigo"
        assert task.task_type == "ride"
        assert task.task_id == TASK_ID
        return SimpleNamespace(
            case=_case(),
            conversation=SimpleNamespace(id=CONVERSATION_ID),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.open_case",
        fake_open_case,
    )
    app.dependency_overrides[require_current_user] = fake_user
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_current_user, None)
        app.dependency_overrides.pop(get_session, None)


def test_user_can_open_support_case_for_task(support_user_client) -> None:
    response = support_user_client.post(
        "/comms/v1/support/cases",
        json={
            "subject": "Ride problem",
            "initial_message": "The driver is not moving",
            "priority": "high",
            "owner_service": "diddigo",
            "task_type": "ride",
            "task_id": str(TASK_ID),
        },
    )

    assert response.status_code == 201
    assert response.json()["id"] == str(CASE_ID)
    assert response.json()["conversation_id"] == str(CONVERSATION_ID)
    assert response.json()["status"] == "open"


@pytest.fixture
def support_service_client(monkeypatch):
    async def fake_session():
        return object()

    def fake_verify(self, token):
        assert token == "service-token"
        return TokenClaims(
            subject="service:backoffice",
            token_type="service",
            role="service",
            status="active",
            claims={
                "client_id": "backoffice-staging-diddicomms",
                "scope": "diddicomms:support-cases:read diddicomms:support-cases:write diddicomms:messages:write",
            },
        )

    async def fake_list_cases(self, *, status=None, owner_service=None, limit=100):
        assert status == "open"
        assert owner_service == "diddigo"
        return [_case()]

    async def fake_assign_case(self, *, case_id, assignee_user_id, actor_service, request_id=None):
        assert case_id == CASE_ID
        assert assignee_user_id == AGENT_ID
        assert actor_service == "service:backoffice"
        return _case(status="assigned", assigned_to_user_id=AGENT_ID)

    async def fake_send_agent_message(
        self,
        *,
        case_id,
        agent_user_id,
        client_message_id,
        body,
        actor_service,
        request_id=None,
    ):
        assert case_id == CASE_ID
        assert agent_user_id == AGENT_ID
        assert client_message_id == "agent-msg-1"
        assert body == "We are checking this."
        return SimpleNamespace(
            created=True,
            message=SimpleNamespace(
                id=MESSAGE_ID,
                conversation_id=CONVERSATION_ID,
                sequence=2,
                sender_user_id=AGENT_ID,
                client_message_id="agent-msg-1",
                body="We are checking this.",
                moderation_status="accepted",
            ),
        )

    monkeypatch.setattr("app_base.core.security.FreeIDTokenVerifier.verify", fake_verify)
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseRepository.list_cases",
        fake_list_cases,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.assign_case",
        fake_assign_case,
    )
    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.send_agent_message",
        fake_send_agent_message,
    )
    app.dependency_overrides[get_session] = fake_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_backoffice_can_list_support_cases(support_service_client) -> None:
    response = support_service_client.get(
        "/comms/v1/support/cases?status=open&owner_service=diddigo",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "backoffice-staging-diddicomms"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(CASE_ID)


def test_backoffice_can_assign_support_case(support_service_client) -> None:
    response = support_service_client.post(
        f"/comms/v1/support/cases/{CASE_ID}/assign",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "backoffice-staging-diddicomms"},
        json={"assignee_user_id": str(AGENT_ID)},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
    assert response.json()["assigned_to_user_id"] == str(AGENT_ID)


def test_backoffice_can_send_agent_message(support_service_client) -> None:
    response = support_service_client.post(
        f"/comms/v1/support/cases/{CASE_ID}/messages",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "backoffice-staging-diddicomms"},
        json={
            "agent_user_id": str(AGENT_ID),
            "client_message_id": "agent-msg-1",
            "body": "We are checking this.",
        },
    )

    assert response.status_code == 200
    assert response.json()["sender_user_id"] == str(AGENT_ID)
    assert response.json()["created"] is True


def _case(*, status: str = "open", assigned_to_user_id=None):
    now = datetime(2026, 10, 11, tzinfo=UTC)
    return SimpleNamespace(
        id=CASE_ID,
        conversation_id=CONVERSATION_ID,
        requester_user_id=REQUESTER_ID,
        owner_service="diddigo",
        task_type="ride",
        task_id=TASK_ID,
        subject="Ride problem",
        status=status,
        priority="high",
        assigned_to_user_id=assigned_to_user_id,
        created_at=now,
        updated_at=now,
        resolved_at=None,
    )
