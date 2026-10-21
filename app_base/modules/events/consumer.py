from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app_base.core.metrics import increment, shared_increment, shared_set_gauge
from app_base.core.settings import settings
from app_base.modules.conversations.domain import ConversationState
from app_base.modules.conversations.infra.repositories import ConversationRepository, SupportCaseRepository
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft
from app_base.modules.events.infra.models import ProcessedEventModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundEvent:
    event_id: UUID
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    aggregate_version: int = 0

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> InboundEvent:
        try:
            envelope: dict[str, Any]
            if "event" in fields:
                decoded = json.loads(fields["event"])
                if not isinstance(decoded, dict):
                    raise ValueError("event must be an object")
                envelope = decoded
            else:
                envelope = fields

            raw_payload = envelope.get("payload", {})
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            aggregate_version = int(envelope.get("aggregate_version") or payload.get("aggregate_version") or 0)
            return cls(
                event_id=UUID(str(envelope["event_id"])),
                event_type=str(envelope["event_type"]),
                aggregate_id=str(envelope.get("aggregate_id", "")),
                payload=payload,
                aggregate_version=aggregate_version,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("INBOUND_EVENT_INVALID") from exc


class SupportEventHandler:
    supported_types = {
        "support.case.message.created",
        "support.case.message.created.v1",
        "support.case.updated",
        "support.case.updated.v1",
        "support.case.assigned",
        "support.case.assigned.v1",
        "support.case.resolved",
        "support.case.resolved.v1",
    }

    async def handle(self, session: AsyncSession, event: InboundEvent) -> None:
        if event.event_type not in self.supported_types:
            return
        case_id = _event_case_id(event)
        support_cases = SupportCaseRepository(session)
        case = await support_cases.find_by_id(case_id)
        if case is None:
            logger.info(
                "support_event_projection_missing",
                extra={"event_id": str(event.event_id), "event_type": event.event_type},
            )
            raise LookupError("SUPPORT_CASE_PROJECTION_NOT_FOUND")
        if event.aggregate_version and event.aggregate_version <= int(case.support_version or 0):
            return

        now = datetime.now(UTC)
        case.projection_status = "synced"
        case.last_reconciled_at = now
        if event.aggregate_version:
            case.support_version = event.aggregate_version

        if "message.created" in event.event_type:
            if event.payload.get("visibility", "user_visible") != "user_visible":
                return
            message_id = event.payload.get("message_id") or event.payload.get("id")
            if not message_id:
                raise ValueError("SUPPORT_MESSAGE_ID_REQUIRED")
            OutboxWriter(session).add(
                OutboxEventDraft(
                    aggregate_type="support_case",
                    aggregate_id=str(case_id),
                    event_type="comms.support.message.created.v1",
                    aggregate_version=event.aggregate_version,
                    causation_id=event.event_id,
                    payload={
                        "case_id": str(case_id),
                        "conversation_id": str(case.conversation_id),
                        "message_id": str(message_id),
                    },
                )
            )
            return

        if status := event.payload.get("status"):
            case.status = str(status)
        if priority := event.payload.get("priority"):
            case.priority = str(priority)
        if "assigned_to_user_id" in event.payload:
            assigned = event.payload.get("assigned_to_user_id")
            case.assigned_to_user_id = UUID(str(assigned)) if assigned else None
        case.updated_at = now

        if "resolved" in event.event_type or case.status == "resolved":
            case.status = "resolved"
            case.resolved_at = now
            conversation = await ConversationRepository(session).find_by_id(case.conversation_id)
            if conversation is not None:
                conversation.state = ConversationState.CLOSED.value
                conversation.closed_at = now
                conversation.updated_at = now


class RedisStreamConsumer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        events_redis: Redis,
        *,
        metrics_redis: Redis | None = None,
        handler: SupportEventHandler | None = None,
        stream_name: str | None = None,
        group_name: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.events_redis = events_redis
        self.metrics_redis = metrics_redis or events_redis
        self.handler = handler or SupportEventHandler()
        self.stream_name = stream_name or settings.support_events_stream
        self.group_name = group_name or settings.support_events_consumer_group
        self.consumer_name = (
            consumer_name
            or settings.support_events_consumer_name
            or f"diddicomms-worker-{socket.gethostname()}"
        )
        self.metrics_key = settings.redis_key("metrics:worker")

    async def ensure_group(self) -> None:
        try:
            await self.events_redis.xgroup_create(self.stream_name, self.group_name, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_once(self, *, count: int = 100, block_ms: int = 1000) -> int:
        batches = await self.events_redis.xreadgroup(
            self.group_name,
            self.consumer_name,
            {self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        return await self._process_batches(batches)

    async def reclaim_once(self, *, count: int = 100) -> int:
        result = await self.events_redis.xautoclaim(
            self.stream_name,
            self.group_name,
            self.consumer_name,
            min_idle_time=settings.event_consumer_reclaim_idle_ms,
            start_id="0-0",
            count=count,
        )
        entries = result[1] if len(result) > 1 else []
        return await self._process_batches([(self.stream_name, entries)] if entries else [])

    async def refresh_metrics(self) -> None:
        groups = await self.events_redis.xinfo_groups(self.stream_name)
        group = next((item for item in groups if item.get("name") == self.group_name), None)
        pending = int(group.get("pending", 0)) if group is not None else 0
        lag_value = group.get("lag", 0) if group is not None else 0
        lag = int(lag_value) if lag_value is not None else 0
        labels = {"stream": self.stream_name, "group": self.group_name}
        await shared_set_gauge(
            self.metrics_redis, self.metrics_key, "diddicomms_inbound_pending_events", pending, labels
        )
        await shared_set_gauge(
            self.metrics_redis, self.metrics_key, "diddicomms_inbound_consumer_lag", lag, labels
        )

    async def _process_batches(self, batches) -> int:
        processed = 0
        for _, entries in batches:
            for stream_id, fields in entries:
                if await self._process_entry(str(stream_id), fields):
                    processed += 1
        return processed

    async def _process_entry(self, stream_id: str, fields: dict[str, str]) -> bool:
        try:
            event = InboundEvent.from_stream_fields(fields)
            async with self.session_factory() as session:
                already_processed = await session.get(
                    ProcessedEventModel,
                    {"consumer_name": self.group_name, "event_id": event.event_id},
                )
                if already_processed is None:
                    await self.handler.handle(session, event)
                    session.add(ProcessedEventModel(consumer_name=self.group_name, event_id=event.event_id))
                    await session.commit()
            await self.events_redis.xack(self.stream_name, self.group_name, stream_id)
            increment("diddicomms_inbound_events_total", {"outcome": "processed"})
            await shared_increment(
                self.metrics_redis, self.metrics_key, "diddicomms_inbound_events_total", {"outcome": "processed"}
            )
            return True
        except Exception as exc:
            logger.warning(
                "inbound_event_failed",
                extra={"stream_id": stream_id, "failure_type": type(exc).__name__},
            )
            if await self._delivery_count(stream_id) >= settings.event_consumer_max_attempts:
                await self.metrics_redis.xadd(
                    settings.inbound_events_dlq_stream,
                    {
                        "source_stream": self.stream_name,
                        "source_stream_id": stream_id,
                        "failure_type": type(exc).__name__,
                    },
                    maxlen=settings.events_dlq_stream_maxlen,
                    approximate=True,
                )
                await self.events_redis.xack(self.stream_name, self.group_name, stream_id)
                increment("diddicomms_inbound_events_total", {"outcome": "dead_lettered"})
                await shared_increment(
                    self.metrics_redis,
                    self.metrics_key,
                    "diddicomms_inbound_events_total",
                    {"outcome": "dead_lettered"},
                )
            else:
                increment("diddicomms_inbound_events_total", {"outcome": "retry"})
                await shared_increment(
                    self.metrics_redis, self.metrics_key, "diddicomms_inbound_events_total", {"outcome": "retry"}
                )
            return False

    async def _delivery_count(self, stream_id: str) -> int:
        pending = await self.events_redis.xpending_range(
            self.stream_name,
            self.group_name,
            min=stream_id,
            max=stream_id,
            count=1,
        )
        if not pending:
            return 1
        item = pending[0]
        return int(item.get("times_delivered", item.get("delivery_count", 1)))


def _event_case_id(event: InboundEvent) -> UUID:
    value = event.payload.get("case_id") or event.aggregate_id
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ValueError("SUPPORT_CASE_ID_INVALID") from exc
