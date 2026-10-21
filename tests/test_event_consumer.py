from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app_base.modules.events.consumer import InboundEvent, SupportEventHandler

CASE_ID = UUID("aaaaaaaa-1111-1111-1111-aaaaaaaaaaaa")
CONVERSATION_ID = UUID("bbbbbbbb-2222-2222-2222-bbbbbbbbbbbb")
EVENT_ID = UUID("cccccccc-3333-3333-3333-cccccccccccc")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, item: object) -> None:
        self.added.append(item)


def test_inbound_event_parses_aggregate_version() -> None:
    event = InboundEvent.from_stream_fields(
        {
            "event_id": str(EVENT_ID),
            "event_type": "support.case.message.created.v1",
            "aggregate_id": str(CASE_ID),
            "aggregate_version": "9",
            "payload": json.dumps({"case_id": str(CASE_ID), "message_id": "message-1"}),
        }
    )

    assert event.event_id == EVENT_ID
    assert event.aggregate_version == 9
    assert event.payload["message_id"] == "message-1"


def test_inbound_event_parses_canonical_diddisupport_envelope() -> None:
    envelope = {
        "event_id": str(EVENT_ID),
        "event_type": "support.case.message.created.v1",
        "aggregate_id": str(CASE_ID),
        "aggregate_version": 9,
        "occurred_at": "2026-10-21T00:00:00+00:00",
        "payload": {
            "case_id": str(CASE_ID),
            "message_id": "message-1",
            "visibility": "user_visible",
        },
    }

    event = InboundEvent.from_stream_fields({"event": json.dumps(envelope)})

    assert event.event_id == EVENT_ID
    assert event.event_type == "support.case.message.created.v1"
    assert event.aggregate_version == 9
    assert event.payload["visibility"] == "user_visible"


@pytest.mark.asyncio
async def test_consumer_routes_stream_operations_and_metrics_to_separate_redis() -> None:
    from app_base.modules.events.consumer import RedisStreamConsumer

    events_redis = AsyncMock()
    metrics_redis = AsyncMock()
    events_redis.xinfo_groups.return_value = [{"name": "diddicomms", "pending": 2, "lag": 4}]
    consumer = RedisStreamConsumer(
        AsyncMock(),
        events_redis,
        metrics_redis=metrics_redis,
        consumer_name="diddicomms-worker-test",
    )

    await consumer.ensure_group()
    await consumer.refresh_metrics()

    events_redis.xgroup_create.assert_awaited_once_with(
        "diddisupport.events", "diddicomms", id="0-0", mkstream=True
    )
    events_redis.xinfo_groups.assert_awaited_once_with("diddisupport.events")
    assert metrics_redis.hset.await_count == 2
    events_redis.hset.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_event_uses_local_dlq_and_source_ack(monkeypatch) -> None:
    from app_base.modules.events.consumer import RedisStreamConsumer

    events_redis = AsyncMock()
    metrics_redis = AsyncMock()
    events_redis.xpending_range.return_value = [{"times_delivered": 5}]
    consumer = RedisStreamConsumer(
        AsyncMock(),
        events_redis,
        metrics_redis=metrics_redis,
        consumer_name="diddicomms-worker-test",
    )

    assert await consumer._process_entry("1-0", {}) is False

    metrics_redis.xadd.assert_awaited_once()
    events_redis.xadd.assert_not_awaited()
    events_redis.xack.assert_awaited_once_with("diddisupport.events", "diddicomms", "1-0")


@pytest.mark.asyncio
async def test_support_message_event_emits_body_free_comms_notification(monkeypatch) -> None:
    case = SimpleNamespace(
        id=CASE_ID,
        conversation_id=CONVERSATION_ID,
        support_version=2,
        projection_status="pending",
        last_reconciled_at=None,
    )

    async def fake_find(self, case_id):
        assert case_id == CASE_ID
        return case

    monkeypatch.setattr(
        "app_base.modules.events.consumer.SupportCaseRepository.find_by_id",
        fake_find,
    )
    session = FakeSession()
    event = InboundEvent(
        event_id=EVENT_ID,
        event_type="support.case.message.created.v1",
        aggregate_id=str(CASE_ID),
        aggregate_version=3,
        payload={
            "case_id": str(CASE_ID),
            "message_id": "dddddddd-4444-4444-4444-dddddddddddd",
            "visibility": "user_visible",
            "body": "must not be copied to the event",
        },
    )

    await SupportEventHandler().handle(session, event)  # type: ignore[arg-type]

    assert case.support_version == 3
    assert case.projection_status == "synced"
    assert len(session.added) == 1
    outbox = session.added[0]
    assert outbox.event_type == "comms.support.message.created.v1"
    assert "body" not in outbox.payload


@pytest.mark.asyncio
async def test_internal_support_note_updates_projection_without_notification(monkeypatch) -> None:
    case = SimpleNamespace(
        id=CASE_ID,
        conversation_id=CONVERSATION_ID,
        support_version=2,
        projection_status="pending",
        last_reconciled_at=None,
    )

    async def fake_find(self, case_id):
        assert case_id == CASE_ID
        return case

    monkeypatch.setattr(
        "app_base.modules.events.consumer.SupportCaseRepository.find_by_id",
        fake_find,
    )
    session = FakeSession()
    event = InboundEvent(
        event_id=EVENT_ID,
        event_type="support.case.message.created.v1",
        aggregate_id=str(CASE_ID),
        aggregate_version=3,
        payload={
            "case_id": str(CASE_ID),
            "message_id": "dddddddd-4444-4444-4444-dddddddddddd",
            "visibility": "internal_note",
        },
    )

    await SupportEventHandler().handle(session, event)  # type: ignore[arg-type]

    assert case.support_version == 3
    assert case.projection_status == "synced"
    assert session.added == []


@pytest.mark.asyncio
async def test_stale_support_event_is_ignored(monkeypatch) -> None:
    case = SimpleNamespace(
        id=CASE_ID,
        conversation_id=CONVERSATION_ID,
        support_version=5,
        projection_status="synced",
        last_reconciled_at=None,
    )

    async def fake_find(self, case_id):
        return case

    monkeypatch.setattr(
        "app_base.modules.events.consumer.SupportCaseRepository.find_by_id",
        fake_find,
    )
    session = FakeSession()
    event = InboundEvent(
        event_id=EVENT_ID,
        event_type="support.case.message.created.v1",
        aggregate_id=str(CASE_ID),
        aggregate_version=4,
        payload={"case_id": str(CASE_ID), "message_id": "message-1"},
    )

    await SupportEventHandler().handle(session, event)  # type: ignore[arg-type]

    assert session.added == []
    assert case.support_version == 5
