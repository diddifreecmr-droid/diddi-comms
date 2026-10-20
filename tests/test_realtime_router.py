import json
from uuid import UUID

from app_base.modules.realtime.router import _event_for_conversation

CONVERSATION_ID = UUID("99999999-9999-9999-9999-999999999999")


def test_realtime_event_is_filtered_and_serialized() -> None:
    event = _event_for_conversation(
        "1740000000000-0",
        {
            "event_type": "comms.message.created.v1",
            "event_version": "1",
            "payload": json.dumps({"conversation_id": str(CONVERSATION_ID), "message_id": "message-1"}),
        },
        CONVERSATION_ID,
    )

    assert event == {
        "event_id": "1740000000000-0",
        "event_type": "comms.message.created.v1",
        "event_version": 1,
        "payload": {"conversation_id": str(CONVERSATION_ID), "message_id": "message-1"},
    }


def test_realtime_event_does_not_cross_conversations() -> None:
    event = _event_for_conversation(
        "1740000000000-0",
        {
            "event_type": "comms.message.created.v1",
            "payload": json.dumps({"conversation_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"}),
        },
        CONVERSATION_ID,
    )

    assert event is None
