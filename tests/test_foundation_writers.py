from unittest.mock import Mock
from uuid import UUID

import pytest

from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import DIDDICOMMS_EVENTS_DLQ_STREAM, DIDDICOMMS_EVENTS_STREAM, OutboxEventDraft


def test_audit_recorder_requires_actor() -> None:
    recorder = AuditRecorder(Mock())

    with pytest.raises(ValueError, match="requires actor"):
        recorder.add(AuditEventDraft(action="message.created", target_type="conversation", outcome="succeeded"))


def test_audit_recorder_adds_safe_event() -> None:
    session = Mock()
    recorder = AuditRecorder(session)

    event = recorder.add(
        AuditEventDraft(
            actor_service="diddicomms",
            action="context.resolved",
            target_type="ride",
            target_id="11111111-1111-1111-1111-111111111111",
            outcome="succeeded",
            safe_metadata={"task_type": "ride"},
        )
    )

    assert event.actor_service == "diddicomms"
    assert event.safe_metadata == {"task_type": "ride"}
    session.add.assert_called_once_with(event)


def test_outbox_writer_adds_event() -> None:
    session = Mock()
    writer = OutboxWriter(session)

    event = writer.add(
        OutboxEventDraft(
            aggregate_type="conversation",
            aggregate_id="11111111-1111-1111-1111-111111111111",
            event_type="comms.conversation.opened",
            correlation_id="request-id",
            causation_id=UUID("22222222-2222-2222-2222-222222222222"),
            payload={"task_type": "ride"},
        )
    )

    assert event.event_version == 1
    assert event.payload == {"task_type": "ride"}
    assert event.correlation_id == "request-id"
    session.add.assert_called_once_with(event)


def test_stream_names_are_fixed() -> None:
    assert DIDDICOMMS_EVENTS_STREAM == "diddicomms.events"
    assert DIDDICOMMS_EVENTS_DLQ_STREAM == "diddicomms.events.dlq"
