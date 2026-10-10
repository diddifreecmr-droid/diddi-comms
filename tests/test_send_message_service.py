from __future__ import annotations

from uuid import UUID

import pytest

from app_base.modules.context.domain import CommunicationContext
from app_base.modules.conversations.application import SendMessageService
from app_base.modules.conversations.infra.models import ConversationModel

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DRIVER_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTSIDER_ID = UUID("44444444-4444-4444-4444-444444444444")


class FakeResolver:
    def __init__(self, context: CommunicationContext) -> None:
        self.context = context

    async def get_task(self, task_type: str, task_id: UUID) -> CommunicationContext:
        return self.context


class FakeScalarResult:
    def __init__(self, value=None) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return []


class FakeSession:
    def __init__(self, conversation=None, existing_message=None) -> None:
        self.conversation = conversation
        self.existing_message = existing_message
        self.added: list[object] = []
        self.execute_count = 0

    async def get(self, model, object_id):
        return self.conversation if object_id == CONVERSATION_ID else None

    async def execute(self, _statement):
        self.execute_count += 1
        if self.execute_count == 1:
            return FakeScalarResult(self.existing_message)
        return FakeScalarResult()

    def add(self, item: object) -> None:
        self.added.append(item)


@pytest.mark.asyncio
async def test_send_message_creates_message_audit_and_outbox_without_body_in_side_channels() -> None:
    session = FakeSession(conversation=_conversation())
    service = SendMessageService(session, resolver_factory=lambda owner: FakeResolver(_context()))  # type: ignore[arg-type]

    result = await service.send(
        conversation_id=CONVERSATION_ID,
        actor_user_id=PASSENGER_ID,
        client_message_id="client-1",
        body="  I am at the gate  ",
        request_id="request-id",
    )

    assert result.created is True
    assert result.message.body == "I am at the gate"
    assert result.message.sequence == 1
    assert len(session.added) == 3
    side_channel_text = str([item.__dict__ for item in session.added if item is not result.message])
    assert "I am at the gate" not in side_channel_text


@pytest.mark.asyncio
async def test_send_message_denies_outsider() -> None:
    service = SendMessageService(
        FakeSession(conversation=_conversation()),
        resolver_factory=lambda owner: FakeResolver(_context()),
    )  # type: ignore[arg-type]

    with pytest.raises(PermissionError, match="ACTOR_NOT_TASK_PARTICIPANT"):
        await service.send(
            conversation_id=CONVERSATION_ID,
            actor_user_id=OUTSIDER_ID,
            client_message_id="client-1",
            body="Hello",
        )


@pytest.mark.asyncio
async def test_send_message_rejects_empty_body() -> None:
    service = SendMessageService(FakeSession(), resolver_factory=lambda owner: FakeResolver(_context()))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="MESSAGE_BODY_EMPTY"):
        await service.send(
            conversation_id=CONVERSATION_ID,
            actor_user_id=PASSENGER_ID,
            client_message_id="client-1",
            body=" ",
        )


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


def _context() -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
            "state": "matched",
            "version": 1,
            "participants": [
                {"user_id": str(PASSENGER_ID), "role": "passenger", "phone_e164": "+237600000001"},
                {"user_id": str(DRIVER_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": True,
            "calling_allowed": True,
            "closes_at": None,
        }
    )

