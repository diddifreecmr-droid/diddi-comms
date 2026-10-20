from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app_base.core.database import async_session_factory
from app_base.core.redis import create_redis
from app_base.core.settings import settings
from app_base.modules.events.infra.models import OutboxEventModel
from app_base.modules.events.infra.redis_streams import RedisStreamPublisher, StreamEvent

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis) -> None:
        self.session_factory = session_factory
        self.publisher = RedisStreamPublisher(redis)

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
        return processed

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
            return
        delay = min(2 ** max(event.attempts - 1, 0), 300)
        event.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)

    @staticmethod
    def _stream_event(event: OutboxEventModel) -> StreamEvent:
        return StreamEvent(
            event_id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload,
            event_version=event.event_version,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            occurred_at=event.created_at or datetime.now(UTC),
        )


async def run_worker() -> None:
    redis = create_redis()
    dispatcher = OutboxDispatcher(async_session_factory, redis)
    try:
        while True:
            processed = await dispatcher.dispatch_once()
            if processed == 0:
                await asyncio.sleep(1)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run_worker())
