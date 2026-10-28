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
from app_base.modules.conversations.presentation.router import _remote_support_message_response
from app_base.modules.support.read_client import SupportMessageResponse

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
        category="general",
        origin_report_id=None,
        initial_message=None,
        task=None,
        request_id=None,
        idempotency_key=None,
    ):
        assert requester_user_id == REQUESTER_ID
        assert subject == "Ride problem"
        assert priority == "high"
        assert category == "general"
        assert origin_report_id is None
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
        headers={"Idempotency-Key": "legacy-support-case-1"},
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


def test_user_can_open_support_conversation_for_task(support_user_client, monkeypatch) -> None:
    async def fake_open_case(self, **kwargs):
        assert kwargs["requester_user_id"] == REQUESTER_ID
        assert kwargs["subject"] == "Payment issue"
        assert kwargs["category"] == "payment_issue"
        assert kwargs["initial_message"] == "The payment is still pending"
        assert kwargs["idempotency_key"] == "support-conversation-1"
        assert kwargs["task"].owner_service == "diddigo"
        assert kwargs["task"].task_type == "ride"
        assert kwargs["task"].task_id == TASK_ID
        return SimpleNamespace(
            case=_case(),
            conversation=SimpleNamespace(id=CONVERSATION_ID, state="active"),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.open_case",
        fake_open_case,
    )
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        headers={"Idempotency-Key": "support-conversation-1"},
        json={
            "category": "payment_issue",
            "message": "The payment is still pending",
            "context": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "conversation_id": str(CONVERSATION_ID),
        "support_case_id": str(CASE_ID),
        "conversation_state": "active",
        "case_status": "open",
        "owner_service": "diddigo",
        "task_type": "ride",
        "task_id": str(TASK_ID),
    }


def test_user_can_open_general_support_conversation(support_user_client, monkeypatch) -> None:
    async def fake_open_case(self, **kwargs):
        assert kwargs["task"] is None
        assert kwargs["subject"] == "Account issue"
        return SimpleNamespace(
            case=_case(owner_service=None, task_type=None, task_id=None),
            conversation=SimpleNamespace(id=CONVERSATION_ID, state="active"),
        )

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.open_case",
        fake_open_case,
    )
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        headers={"Idempotency-Key": "general-support-1"},
        json={"category": "account_issue", "message": "I cannot update my account"},
    )

    assert response.status_code == 201
    assert response.json()["owner_service"] is None
    assert response.json()["task_id"] is None


def test_support_conversation_context_is_atomic(support_user_client) -> None:
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        headers={"Idempotency-Key": "invalid-context-1"},
        json={
            "category": "ride_issue",
            "message": "Help",
            "context": {"owner_service": "diddigo", "task_type": "ride"},
        },
    )

    assert response.status_code == 422


def test_support_conversation_requires_idempotency_key(support_user_client) -> None:
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        json={"category": "account_issue", "message": "Help with my account"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_support_conversation_hides_foreign_task(support_user_client, monkeypatch) -> None:
    async def fake_open_case(self, **kwargs):
        raise PermissionError("ACTOR_NOT_TASK_PARTICIPANT")

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseService.open_case",
        fake_open_case,
    )
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        headers={"Idempotency-Key": "foreign-task-1"},
        json={
            "category": "ride_issue",
            "message": "This ride is not mine",
            "context": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_support_category_must_match_context(support_user_client) -> None:
    response = support_user_client.post(
        "/comms/v1/support/conversations",
        headers={"Idempotency-Key": "invalid-category-context-1"},
        json={"category": "ride_issue", "message": "This has no ride context"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUPPORT_CATEGORY_CONTEXT_INVALID"


def test_user_can_list_official_categories_for_ride(support_user_client) -> None:
    response = support_user_client.get(
        "/comms/v1/support/categories?owner_service=diddigo&task_type=ride",
    )

    assert response.status_code == 200
    category_ids = {item["id"] for item in response.json()}
    assert {"general", "account_issue", "payment_issue", "ride_issue", "other"}.issubset(category_ids)
    assert "delivery_issue" not in category_ids
    ride = next(item for item in response.json() if item["id"] == "ride_issue")
    assert ride["contexts"] == [{"owner_service": "diddigo", "task_type": "ride"}]


def test_user_can_page_own_support_conversations(support_user_client, monkeypatch) -> None:
    second_case_id = UUID("dddddddd-4444-4444-4444-dddddddddddd")
    second_conversation_id = UUID("eeeeeeee-5555-5555-5555-eeeeeeeeeeee")
    first = _case()
    second = _case()
    second.id = second_case_id
    second.conversation_id = second_conversation_id
    second.category = "account_issue"

    async def fake_list_for_requester(
        self,
        *,
        requester_user_id,
        status=None,
        before_updated_at=None,
        before_id=None,
        limit=20,
    ):
        assert requester_user_id == REQUESTER_ID
        assert status == "open"
        assert before_updated_at is None
        assert before_id is None
        assert limit == 2
        return [first, second]

    monkeypatch.setattr(
        "app_base.modules.conversations.presentation.router.SupportCaseRepository.list_for_requester",
        fake_list_for_requester,
    )
    response = support_user_client.get("/comms/v1/support/conversations?status=open&limit=1")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["conversation_id"] == str(CONVERSATION_ID)
    assert response.json()["items"][0]["category"] == "general"
    assert response.json()["next_cursor"]


def test_support_conversation_cursor_is_opaque_and_validated(support_user_client) -> None:
    response = support_user_client.get("/comms/v1/support/conversations?cursor=not-a-valid-cursor")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SUPPORT_CURSOR_INVALID"


def test_remote_support_message_exposes_timestamp_and_agent_author() -> None:
    response = _remote_support_message_response(
        SupportMessageResponse(
            message_id=MESSAGE_ID,
            case_id=CASE_ID,
            author_type="agent",
            author_id=str(AGENT_ID),
            body="We are checking this.",
            created_at=datetime(2026, 10, 28, 12, 5, tzinfo=UTC),
        ),
        conversation_id=CONVERSATION_ID,
        sequence=2,
    )

    assert response.created_at == datetime(2026, 10, 28, 12, 5, tzinfo=UTC)
    assert response.sender_type == "support_agent"
    assert response.sender_role == "support_agent"


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


def test_legacy_backoffice_assignment_redirects_to_diddisupport(support_service_client) -> None:
    response = support_service_client.post(
        f"/comms/v1/support/cases/{CASE_ID}/assign",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "backoffice-staging-diddicomms"},
        json={"assignee_user_id": str(AGENT_ID)},
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "DIDDISUPPORT_BACKOFFICE_REQUIRED"


def test_legacy_agent_message_redirects_to_diddisupport(support_service_client) -> None:
    response = support_service_client.post(
        f"/comms/v1/support/cases/{CASE_ID}/messages",
        headers={"Authorization": "Bearer service-token", "X-Client-ID": "backoffice-staging-diddicomms"},
        json={
            "agent_user_id": str(AGENT_ID),
            "client_message_id": "agent-msg-1",
            "body": "We are checking this.",
        },
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "DIDDISUPPORT_BACKOFFICE_REQUIRED"


def _case(
    *,
    status: str = "open",
    assigned_to_user_id=None,
    owner_service="diddigo",
    task_type="ride",
    task_id=TASK_ID,
):
    now = datetime(2026, 10, 11, tzinfo=UTC)
    return SimpleNamespace(
        id=CASE_ID,
        conversation_id=CONVERSATION_ID,
        requester_user_id=REQUESTER_ID,
        owner_service=owner_service,
        task_type=task_type,
        task_id=task_id,
        subject="Ride problem",
        category="general",
        status=status,
        priority="high",
        assigned_to_user_id=assigned_to_user_id,
        created_at=now,
        updated_at=now,
        resolved_at=None,
    )
