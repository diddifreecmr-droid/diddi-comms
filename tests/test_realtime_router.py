import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app_base.core.errors import ApiError
from app_base.modules.realtime.router import _authentication_token, _event_for_conversation, _stream_id_tuple

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


def test_realtime_includes_delivery_events_and_orders_stream_ids() -> None:
    event = _event_for_conversation(
        "20-1",
        {
            "event_type": "comms.message.delivered.v1",
            "event_version": "1",
            "payload": json.dumps({"conversation_id": str(CONVERSATION_ID), "message_id": "message-1"}),
        },
        CONVERSATION_ID,
    )

    assert event is not None
    assert event["event_type"] == "comms.message.delivered.v1"
    assert _stream_id_tuple("20-1") > _stream_id_tuple("19-99")


def test_realtime_accepts_native_authorization_header() -> None:
    websocket = SimpleNamespace(headers={"authorization": "Bearer user-jwt", "sec-websocket-protocol": "diddicomms.v1"})

    assert _authentication_token(websocket) == ("user-jwt", "diddicomms.v1")


def test_realtime_accepts_browser_subprotocol_authentication() -> None:
    websocket = SimpleNamespace(
        headers={"sec-websocket-protocol": "diddicomms.v1, diddicomms.auth.header.payload.signature"}
    )

    assert _authentication_token(websocket) == ("header.payload.signature", "diddicomms.v1")


def test_realtime_rejects_auth_subprotocol_without_version_protocol() -> None:
    websocket = SimpleNamespace(headers={"sec-websocket-protocol": "diddicomms.auth.header.payload.signature"})

    with pytest.raises(ApiError, match="Authentication is required"):
        _authentication_token(websocket)
