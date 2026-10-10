from __future__ import annotations

from unittest.mock import Mock
from uuid import UUID

import pytest

from app_base.modules.context.domain import CommunicationContext, TaskReference
from app_base.modules.conversations.application import EnsureTaskConversationService

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DRIVER_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTSIDER_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeResolver:
    async def get_task(self, task_type: str, task_id: UUID) -> CommunicationContext:
        assert task_type == "ride"
        assert task_id == TASK_ID
        return _context()


class FakeScalarResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, existing=None) -> None:
        self.existing = existing
        self.added: list[object] = []

    async def execute(self, _statement):
        return FakeScalarResult(self.existing)

    def add(self, item: object) -> None:
        self.added.append(item)


@pytest.mark.asyncio
async def test_ensure_creates_conversation_for_task_participant() -> None:
    session = FakeSession()
    service = EnsureTaskConversationService(session, resolver_factory=lambda owner: FakeResolver())  # type: ignore[arg-type]

    result = await service.ensure(
        task=TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID),
        actor_user_id=PASSENGER_ID,
        request_id="request-id",
    )

    assert result.created is True
    assert result.conversation.owner_service == "diddigo"
    assert result.conversation.task_type == "ride"
    assert result.conversation.task_id == TASK_ID
    assert result.conversation.state == "active"
    assert len(session.added) == 5
    assert all(not hasattr(item, "phone_e164") for item in session.added)


@pytest.mark.asyncio
async def test_ensure_returns_existing_conversation() -> None:
    existing = Mock(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        owner_service="diddigo",
        task_type="ride",
        task_id=TASK_ID,
    )
    session = FakeSession(existing=existing)
    service = EnsureTaskConversationService(session, resolver_factory=lambda owner: FakeResolver())  # type: ignore[arg-type]

    result = await service.ensure(
        task=TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID),
        actor_user_id=PASSENGER_ID,
    )

    assert result.created is False
    assert result.conversation is existing


@pytest.mark.asyncio
async def test_ensure_denies_outsider() -> None:
    service = EnsureTaskConversationService(FakeSession(), resolver_factory=lambda owner: FakeResolver())  # type: ignore[arg-type]

    with pytest.raises(PermissionError, match="ACTOR_NOT_TASK_PARTICIPANT"):
        await service.ensure(
            task=TaskReference(owner_service="diddigo", task_type="ride", task_id=TASK_ID),
            actor_user_id=OUTSIDER_ID,
        )


def _context() -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
            "state": "matched",
            "version": 1791633600,
            "participants": [
                {"user_id": str(PASSENGER_ID), "role": "passenger", "phone_e164": "+237600000001"},
                {"user_id": str(DRIVER_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": True,
            "calling_allowed": True,
            "closes_at": None,
        }
    )
