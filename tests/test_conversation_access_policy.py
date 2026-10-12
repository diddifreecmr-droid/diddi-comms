from datetime import UTC, datetime, timedelta
from uuid import UUID

from app_base.modules.context.domain import CommunicationContext
from app_base.modules.conversations.domain import (
    CommunicationAction,
    ConversationAccessPolicy,
    ConversationAccessSnapshot,
    ConversationState,
)

TASK_ID = UUID("11111111-1111-1111-1111-111111111111")
PASSENGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DRIVER_ID = UUID("33333333-3333-3333-3333-333333333333")
OUTSIDER_ID = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_policy_allows_message_between_participants_on_same_open_task() -> None:
    context = _context(closes_at=NOW + timedelta(hours=1))
    conversation = _conversation(closes_at=NOW + timedelta(hours=1))

    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=context,
        conversation=conversation,
        now=NOW,
    )

    assert decision.allowed is True


def test_policy_allows_open_conversation_for_participant_when_any_channel_allowed() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.OPEN_CONVERSATION,
        actor_user_id=PASSENGER_ID,
        context=_context(messaging_allowed=False, calling_allowed=True),
        now=NOW,
    )

    assert decision.allowed is True


def test_policy_rejects_open_conversation_when_owner_disallows_all_channels() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.OPEN_CONVERSATION,
        actor_user_id=PASSENGER_ID,
        context=_context(messaging_allowed=False, calling_allowed=False),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "COMMUNICATION_NOT_ALLOWED_BY_OWNER"


def test_policy_rejects_actor_who_is_not_task_participant() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=OUTSIDER_ID,
        target_user_id=DRIVER_ID,
        context=_context(),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "ACTOR_NOT_TASK_PARTICIPANT"


def test_policy_rejects_target_who_is_not_task_participant() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.CALL,
        actor_user_id=PASSENGER_ID,
        target_user_id=OUTSIDER_ID,
        context=_context(),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TARGET_NOT_TASK_PARTICIPANT"


def test_policy_rejects_call_when_owner_disallows_calling() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.CALL,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(calling_allowed=False),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "CALLING_NOT_ALLOWED_BY_OWNER"


def test_policy_rejects_message_after_owner_window_closes() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(closes_at=NOW),
        conversation=_conversation(closes_at=NOW + timedelta(minutes=5)),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TASK_COMMUNICATION_WINDOW_CLOSED"


def test_policy_rejects_message_after_conversation_window_closes() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(closes_at=NOW + timedelta(minutes=5)),
        conversation=_conversation(closes_at=NOW),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "CONVERSATION_WINDOW_CLOSED"


def test_policy_rejects_mismatched_task_reference() -> None:
    conversation = _conversation()
    context = _context(task_id=UUID("55555555-5555-5555-5555-555555555555"))

    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=context,
        conversation=conversation,
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TASK_REFERENCE_MISMATCH"


def test_policy_allows_history_read_after_window_closes_for_participant() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.READ_HISTORY,
        actor_user_id=PASSENGER_ID,
        context=_context(closes_at=NOW),
        conversation=_conversation(state=ConversationState.CLOSED, closes_at=NOW),
        now=NOW,
    )

    assert decision.allowed is True


def test_policy_rejects_message_after_terminal_task_state_without_owner_window() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(state="cancelled", closes_at=None),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TASK_TERMINAL_STATE_REQUIRES_COMMUNICATION_WINDOW"


def test_policy_rejects_message_after_qualified_cancelled_state_without_owner_window() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(state="cancelled_by_passenger", closes_at=None),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TASK_TERMINAL_STATE_REQUIRES_COMMUNICATION_WINDOW"


def test_policy_allows_message_after_terminal_task_state_inside_owner_window() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(state="completed", closes_at=NOW + timedelta(hours=24)),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is True


def test_policy_rejects_message_after_terminal_task_state_when_owner_window_passed() -> None:
    decision = ConversationAccessPolicy().decide(
        action=CommunicationAction.MESSAGE,
        actor_user_id=PASSENGER_ID,
        target_user_id=DRIVER_ID,
        context=_context(state="completed", closes_at=NOW),
        conversation=_conversation(),
        now=NOW,
    )

    assert decision.allowed is False
    assert decision.reason_code == "TASK_COMMUNICATION_WINDOW_CLOSED"


def _context(
    *,
    task_id: UUID = TASK_ID,
    state: str = "driver_assigned",
    messaging_allowed: bool = True,
    calling_allowed: bool = True,
    closes_at: datetime | None = None,
) -> CommunicationContext:
    return CommunicationContext.model_validate(
        {
            "task": {
                "owner_service": "diddigo",
                "task_type": "ride",
                "task_id": str(task_id),
            },
            "state": state,
            "version": 12,
            "participants": [
                {"user_id": str(PASSENGER_ID), "role": "passenger", "phone_e164": "+237600000001"},
                {"user_id": str(DRIVER_ID), "role": "driver", "phone_e164": "+237600000002"},
            ],
            "messaging_allowed": messaging_allowed,
            "calling_allowed": calling_allowed,
            "closes_at": closes_at.isoformat() if closes_at else None,
        }
    )


def _conversation(
    *,
    state: ConversationState = ConversationState.ACTIVE,
    closes_at: datetime | None = None,
) -> ConversationAccessSnapshot:
    return ConversationAccessSnapshot(task=_context().task, state=state, closes_at=closes_at)
