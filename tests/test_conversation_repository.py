from uuid import UUID

from app_base.modules.context.domain import CommunicationContext
from app_base.modules.conversations.infra.repositories import build_task_conversation

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DRIVER_ID = UUID("33333333-3333-3333-3333-333333333333")


def test_build_task_conversation_stores_task_reference_and_user_participants_only() -> None:
    draft = build_task_conversation(_context(), conversation_id=CONVERSATION_ID)

    assert draft.conversation.owner_service == "diddigo"
    assert draft.conversation.task_type == "ride"
    assert draft.conversation.task_id == TASK_ID
    assert draft.conversation.task_version == 12
    assert draft.conversation.state == "active"
    assert {participant.user_id for participant in draft.participants} == {PASSENGER_ID, DRIVER_ID}
    assert {participant.role for participant in draft.participants} == {"passenger", "driver"}
    assert all(participant.conversation_id == CONVERSATION_ID for participant in draft.participants)
    assert all(not hasattr(participant, "phone_e164") for participant in draft.participants)


def _context() -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(TASK_ID),
            },
            "state": "driver_assigned",
            "version": 12,
            "participants": [
                {"user_id": str(PASSENGER_ID), "role": "passenger", "phone_e164": "+237600000001"},
                {"user_id": str(DRIVER_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": True,
            "calling_allowed": True,
            "closes_at": None,
        }
    )

