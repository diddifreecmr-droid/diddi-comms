from datetime import UTC, datetime
from uuid import UUID

import pytest

from app_base.modules.events.domain import DIDDICOMMS_EVENTS_STREAM
from app_base.modules.events.infra.redis_streams import RedisStreamPublisher, StreamEvent


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream_name: str, fields: dict[str, str], **kwargs) -> str:
        self.calls.append((stream_name, fields))
        return "1-0"


def test_stream_event_fields_are_privacy_safe_envelope() -> None:
    event = StreamEvent(
        event_id=UUID("11111111-1111-1111-1111-111111111111"),
        event_type="comms.message.created",
        aggregate_type="conversation",
        aggregate_id="22222222-2222-2222-2222-222222222222",
        aggregate_version=1,
        correlation_id="request-id",
        occurred_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
        payload={"sequence": 1, "task_type": "ride"},
    )

    assert event.to_stream_fields() == {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "event_type": "comms.message.created",
        "event_version": "1",
        "aggregate_version": "1",
        "occurred_at": "2026-10-09T12:00:00Z",
        "producer": "diddicomms",
        "aggregate_type": "conversation",
        "aggregate_id": "22222222-2222-2222-2222-222222222222",
        "correlation_id": "request-id",
        "causation_id": "",
        "payload": '{"sequence":1,"task_type":"ride"}',
    }


@pytest.mark.asyncio
async def test_redis_stream_publisher_uses_fixed_stream() -> None:
    redis = FakeRedis()
    publisher = RedisStreamPublisher(redis)  # type: ignore[arg-type]
    event = StreamEvent(
        event_id=UUID("11111111-1111-1111-1111-111111111111"),
        event_type="comms.message.created",
        aggregate_type="conversation",
        aggregate_id="22222222-2222-2222-2222-222222222222",
    )

    entry_id = await publisher.publish(event)

    assert entry_id == "1-0"
    assert redis.calls[0][0] == DIDDICOMMS_EVENTS_STREAM
