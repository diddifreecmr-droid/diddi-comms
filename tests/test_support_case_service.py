from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from app_base.modules.context.domain import CommunicationContext, TaskReference
from app_base.modules.conversations.application import SupportCaseService
from app_base.modules.conversations.infra.models import MessageModel, SupportCaseModel

CASE_ID = UUID("aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")
MESSAGE_ID = UUID("bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb")
TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
REQUESTER_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def get(self, model, object_id):
        return None

    def add(self, item: object) -> None:
        self.added.append(item)


class FakeResolver:
    async def get_task(self, task_type, task_id):
        return CommunicationContext.model_validate(
            {
                "task": {"owner_service": "diddigo", "task_type": "ride", "task_id": str(TASK_ID)},
                "state": "matched",
                "version": 1,
                "participants": [{"user_id": str(REQUESTER_ID), "role": "passenger"}],
                "messaging_allowed": True,
                "calling_allowed": True,
            }
        )


class FakeSupportClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.create_kwargs = None

    async def create_case(self, **kwargs):
        self.calls.append("create_case")
        self.create_kwargs = kwargs
        return SimpleNamespace(case_id=CASE_ID, status="open", created_at=datetime.now(UTC))

    async def send_user_message(self, **kwargs):
        self.calls.append("send_user_message")
        assert kwargs["case_id"] == CASE_ID
        assert kwargs["reporter_user_id"] == REQUESTER_ID
        assert kwargs["idempotency_key"] == f"{self.create_kwargs['idempotency_key']}:initial-message"
        return SimpleNamespace(message_id=MESSAGE_ID)


@pytest.mark.asyncio
async def test_open_case_confirms_remote_case_and_initial_message_before_projection() -> None:
    session = FakeSession()
    support = FakeSupportClient()
    service = SupportCaseService(
        session,  # type: ignore[arg-type]
        resolver_factory=lambda owner: FakeResolver(),
        support_client=support,  # type: ignore[arg-type]
    )

    result = await service.open_case(
        requester_user_id=REQUESTER_ID,
        subject="Ride issue",
        initial_message="Please help",
        task=TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID),
        idempotency_key="case-1",
    )

    assert support.calls == ["create_case", "send_user_message"]
    assert result.case.id == CASE_ID
    assert result.case.external_case_id == CASE_ID
    assert result.case.projection_status == "synced"
    projected_message = next(item for item in session.added if isinstance(item, MessageModel))
    assert projected_message.id == MESSAGE_ID
    assert any(isinstance(item, SupportCaseModel) for item in session.added)


@pytest.mark.asyncio
async def test_open_general_case_does_not_call_a_business_resolver() -> None:
    session = FakeSession()
    support = FakeSupportClient()

    def resolver_factory(owner):
        raise AssertionError(f"unexpected resolver call for {owner}")

    service = SupportCaseService(
        session,  # type: ignore[arg-type]
        resolver_factory=resolver_factory,
        support_client=support,  # type: ignore[arg-type]
    )

    result = await service.open_case(
        requester_user_id=REQUESTER_ID,
        subject="Account issue",
        initial_message="Please help with my account",
        category="account_issue",
        task=None,
        idempotency_key="general-case-1",
    )

    assert result.case.owner_service is None
    assert result.case.task_type is None
    assert result.case.task_id is None
    assert support.create_kwargs["origin_service"] is None
    assert support.create_kwargs["resource_type"] is None
    assert support.create_kwargs["resource_id"] is None
