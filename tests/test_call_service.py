from __future__ import annotations

from uuid import UUID

import pytest

from app_base.modules.calls.application import CreateCallAttemptService
from app_base.modules.context.domain import CommunicationContext
from app_base.modules.conversations.infra.models import CallAttemptModel, ConversationModel

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
ACTOR_ID = UUID("22222222-2222-2222-2222-222222222222")
TARGET_ID = UUID("33333333-3333-3333-3333-333333333333")
ATTEMPT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


class FakeResolver:
    def __init__(self, context: CommunicationContext) -> None:
        self.context = context

    async def get_task(self, task_type: str, task_id: UUID) -> CommunicationContext:
        return self.context


class FakeScalarResult:
    def __init__(self, value) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *, conversation: ConversationModel, attempt: CallAttemptModel) -> None:
        self.conversation = conversation
        self.attempt = attempt
        self.added: list[object] = []

    async def execute(self, statement):
        return FakeScalarResult(self.attempt)

    async def get(self, model, object_id):
        return self.conversation if object_id == CONVERSATION_ID else None

    def add(self, item: object) -> None:
        self.added.append(item)


@pytest.mark.asyncio
async def test_idempotent_call_replay_rechecks_current_task_membership() -> None:
    session = FakeSession(conversation=_conversation(), attempt=_attempt())
    service = CreateCallAttemptService(
        session,  # type: ignore[arg-type]
        resolver_factory=lambda owner: FakeResolver(_context_without_actor()),
    )

    with pytest.raises(PermissionError, match="ACTOR_NOT_TASK_PARTICIPANT"):
        await service.create(
            conversation_id=CONVERSATION_ID,
            actor_user_id=ACTOR_ID,
            target_user_id=TARGET_ID,
            idempotency_key="call-1",
        )

    assert all(not isinstance(item, CallAttemptModel) for item in session.added)


def _conversation() -> ConversationModel:
    return ConversationModel(
        id=CONVERSATION_ID,
        conversation_type="task",
        owner_service="diddigo",
        task_type="ride",
        task_id=TASK_ID,
        state="active",
        task_version=1,
        last_sequence=0,
    )


def _attempt() -> CallAttemptModel:
    return CallAttemptModel(
        id=ATTEMPT_ID,
        conversation_id=CONVERSATION_ID,
        actor_user_id=ACTOR_ID,
        target_user_id=TARGET_ID,
        idempotency_key="call-1",
        outcome="authorized",
    )


def _context_without_actor() -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {"owner_service": "diddigo", "task_type": "ride", "task_id": str(TASK_ID)},
            "state": "matched",
            "version": 2,
            "participants": [
                {"user_id": str(TARGET_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": True,
            "calling_allowed": True,
        }
    )
