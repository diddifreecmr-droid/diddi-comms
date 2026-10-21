from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis

from app_base.core.settings import settings
from app_base.modules.events.domain import DIDDICOMMS_EVENTS_DLQ_STREAM, DIDDICOMMS_EVENTS_STREAM


@dataclass(frozen=True)
class StreamEvent:
    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict = field(default_factory=dict)
    event_version: int = 1
    aggregate_version: int = 0
    producer: str = "diddicomms"
    correlation_id: str | None = None
    causation_id: UUID | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "event_version": str(self.event_version),
            "aggregate_version": str(self.aggregate_version),
            "occurred_at": _iso(self.occurred_at),
            "producer": self.producer,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": self.aggregate_id,
            "correlation_id": self.correlation_id or "",
            "causation_id": str(self.causation_id) if self.causation_id else "",
            "payload": json.dumps(self.payload, separators=(",", ":"), sort_keys=True),
        }


class RedisStreamPublisher:
    def __init__(self, redis: Redis, stream_name: str = DIDDICOMMS_EVENTS_STREAM) -> None:
        self.redis = redis
        self.stream_name = stream_name

    async def publish(self, event: StreamEvent) -> str:
        entry_id = await self.redis.xadd(
            self.stream_name,
            event.to_stream_fields(),
            maxlen=settings.events_stream_maxlen,
            approximate=True,
        )
        return str(entry_id)

    async def publish_dlq(self, event: StreamEvent, *, failure_reason: str) -> str:
        fields = event.to_stream_fields()
        fields["failure_reason"] = failure_reason[:500]
        entry_id = await self.redis.xadd(
            DIDDICOMMS_EVENTS_DLQ_STREAM,
            fields,
            maxlen=settings.events_dlq_stream_maxlen,
            approximate=True,
        )
        return str(entry_id)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

