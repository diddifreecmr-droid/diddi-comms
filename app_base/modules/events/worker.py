from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app_base.core.database import async_session_factory, engine
from app_base.core.metrics import shared_increment, shared_set_gauge
from app_base.core.redis import create_redis, create_support_events_redis
from app_base.core.settings import settings
from app_base.core.tracing import configure_worker_tracing
from app_base.modules.events.consumer import RedisStreamConsumer
from app_base.modules.events.infra.models import OutboxEventModel
from app_base.modules.events.infra.redis_streams import RedisStreamPublisher, StreamEvent

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        self.session_factory = session_factory
        self.redis = redis
        self.publisher = RedisStreamPublisher(redis)
        self.metrics_key = settings.redis_key("metrics:worker")

    async def dispatch_once(self, *, limit: int = 100) -> int:
        processed = 0
        for _ in range(limit):
            async with self.session_factory() as session:
                event = await self._claim_one(session)
                if event is None:
                    await session.rollback()
                    break
                try:
                    stream_id = await self.publisher.publish(self._stream_event(event))
                except Exception as exc:
                    await self._record_failure(session, event, exc)
                    await session.commit()
                    logger.warning("outbox_publish_failed", extra={"event_id": str(event.id)})
                    continue
                event.published_at = datetime.now(UTC)
                event.redis_stream_id = stream_id
                event.updated_at = datetime.now(UTC)
                await session.commit()
                processed += 1
                await shared_increment(
                    self.redis, self.metrics_key, "diddicomms_outbox_events_total", {"outcome": "published"}
                )
        return processed

    async def refresh_metrics(self) -> None:
        async with self.session_factory() as session:
            now = datetime.now(UTC)
            result = await session.execute(
                select(func.count(), func.min(OutboxEventModel.created_at)).where(
                    OutboxEventModel.published_at.is_(None),
                    OutboxEventModel.terminal_failure_reason.is_(None),
                )
            )
            pending, oldest = result.one()
        age_seconds = max((now - oldest).total_seconds(), 0) if oldest is not None else 0
        await shared_set_gauge(
            self.redis, self.metrics_key, "diddicomms_outbox_pending_events", int(pending or 0)
        )
        await shared_set_gauge(self.redis, self.metrics_key, "diddicomms_outbox_oldest_event_age_seconds", age_seconds)

    async def _claim_one(self, session: AsyncSession) -> OutboxEventModel | None:
        now = datetime.now(UTC)
        result = await session.execute(
            select(OutboxEventModel)
            .where(
                OutboxEventModel.published_at.is_(None),
                OutboxEventModel.terminal_failure_reason.is_(None),
                (OutboxEventModel.next_attempt_at.is_(None) | (OutboxEventModel.next_attempt_at <= now)),
            )
            .order_by(OutboxEventModel.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return result.scalar_one_or_none()

    async def _record_failure(self, session: AsyncSession, event: OutboxEventModel, exc: Exception) -> None:
        event.attempts = int(event.attempts or 0) + 1
        event.updated_at = datetime.now(UTC)
        reason = type(exc).__name__
        if event.attempts >= settings.outbox_max_attempts:
            event.terminal_failure_reason = reason
            await self.publisher.publish_dlq(self._stream_event(event), failure_reason=reason)
            await shared_increment(
                self.redis, self.metrics_key, "diddicomms_outbox_events_total", {"outcome": "dead_lettered"}
            )
            return
        delay = min(2 ** max(event.attempts - 1, 0), 300)
        event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
        await shared_increment(self.redis, self.metrics_key, "diddicomms_outbox_events_total", {"outcome": "retry"})

    @staticmethod
    def _stream_event(event: OutboxEventModel) -> StreamEvent:
        return StreamEvent(
            event_id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            event_version=event.event_version,
            aggregate_version=event.aggregate_version,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            occurred_at=event.created_at or datetime.now(UTC),
        )


async def run_worker() -> None:
    configure_worker_tracing(
        engine,
        endpoint=settings.otel_exporter_otlp_endpoint,
        service_name=f"{settings.app_name}-worker",
    )
    local_redis = create_redis()
    support_events_redis = create_support_events_redis()
    dispatcher = OutboxDispatcher(async_session_factory, local_redis)
    consumer = RedisStreamConsumer(
        async_session_factory,
        support_events_redis,
        metrics_redis=local_redis,
    )
    try:
        consecutive_failures = 0
        group_ready = False
        loops = 0
        last_metrics_refresh = 0.0
        while True:
            try:
                if not group_ready:
                    await consumer.ensure_group()
                    group_ready = True
                processed = await dispatcher.dispatch_once()
                consumed = await consumer.read_once(block_ms=1000)
                loops += 1
                if loops % 60 == 0:
                    consumed += await consumer.reclaim_once()
                now = time.monotonic()
                if now - last_metrics_refresh >= settings.worker_metrics_refresh_seconds:
                    await dispatcher.refresh_metrics()
                    await consumer.refresh_metrics()
                    await shared_set_gauge(
                        local_redis,
                        settings.redis_key("metrics:worker"),
                        "diddicomms_worker_last_success_unixtime",
                        time.time(),
                    )
                    last_metrics_refresh = now
                consecutive_failures = 0
                await shared_set_gauge(
                    local_redis, settings.redis_key("metrics:worker"), "diddicomms_worker_consecutive_failures", 0
                )
                if processed == 0 and consumed == 0:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_failures += 1
                group_ready = False
                with suppress(Exception):
                    await shared_set_gauge(
                        local_redis,
                        settings.redis_key("metrics:worker"),
                        "diddicomms_worker_consecutive_failures",
                        consecutive_failures,
                    )
                delay = min(2 ** min(consecutive_failures - 1, 10), settings.worker_retry_max_seconds)
                logger.error(
                    "worker_loop_failed",
                    extra={"failure_type": type(exc).__name__, "retry_seconds": delay},
                )
                await asyncio.sleep(delay)
    finally:
        await support_events_redis.aclose()
        await local_redis.aclose()


if __name__ == "__main__":
    asyncio.run(run_worker())
