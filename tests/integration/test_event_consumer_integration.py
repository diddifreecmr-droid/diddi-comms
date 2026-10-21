from __future__ import annotations

import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app_base.core.database import async_session_factory
from app_base.core.redis import create_redis
from app_base.modules.conversations.infra.models import ConversationModel, SupportCaseModel
from app_base.modules.events.consumer import RedisStreamConsumer
from app_base.modules.events.infra.models import OutboxEventModel, ProcessedEventModel

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION_TESTS") != "1", reason="requires live PostgreSQL and Redis"),
]


@pytest.mark.asyncio(loop_scope="module")
async def test_support_event_commits_projection_before_acknowledgement() -> None:
    event_id = uuid4()
    case_id = uuid4()
    conversation_id = uuid4()
    stream = f"diddicomms.test.support.{event_id}"
    group = f"diddicomms-test-{event_id}"
    redis = create_redis()

    try:
        async with async_session_factory() as session:
            session.add(
                ConversationModel(
                    id=conversation_id,
                    conversation_type="support",
                    owner_service="diddisupport",
                    task_type="support_case",
                    task_id=case_id,
                    state="open",
                )
            )
            session.add(
                SupportCaseModel(
                    id=case_id,
                    external_case_id=case_id,
                    conversation_id=conversation_id,
                    requester_user_id=uuid4(),
                    subject="integration test",
                    status="open",
                    priority="normal",
                    projection_status="pending",
                    support_version=1,
                )
            )
            await session.commit()

        consumer = RedisStreamConsumer(
            async_session_factory,
            redis,
            stream_name=stream,
            group_name=group,
            consumer_name="integration-consumer",
        )
        await consumer.ensure_group()
        await redis.xadd(
            stream,
            {
                "event_id": str(event_id),
                "event_type": "support.case.resolved.v1",
                "aggregate_id": str(case_id),
                "aggregate_version": "2",
                "payload": json.dumps({"case_id": str(case_id), "status": "resolved"}),
            },
        )

        assert await consumer.read_once(block_ms=10) == 1

        async with async_session_factory() as session:
            case = await session.get(SupportCaseModel, case_id)
            processed = await session.get(
                ProcessedEventModel,
                {"consumer_name": group, "event_id": event_id},
            )
            outbox = await session.scalar(select(OutboxEventModel).where(OutboxEventModel.causation_id == event_id))
            assert case is not None
            assert case.status == "resolved"
            assert case.support_version == 2
            assert case.projection_status == "synced"
            assert processed is not None
            assert outbox is None

        assert (await redis.xpending(stream, group))["pending"] == 0
    finally:
        async with async_session_factory() as session:
            await session.execute(delete(ProcessedEventModel).where(ProcessedEventModel.event_id == event_id))
            await session.execute(delete(OutboxEventModel).where(OutboxEventModel.causation_id == event_id))
            await session.execute(delete(ConversationModel).where(ConversationModel.id == conversation_id))
            await session.commit()
        await redis.delete(stream)
        await redis.aclose()


@pytest.mark.asyncio(loop_scope="module")
async def test_canonical_visible_internal_and_duplicate_support_events() -> None:
    visible_event_id = uuid4()
    internal_event_id = uuid4()
    case_id = uuid4()
    conversation_id = uuid4()
    stream = f"diddicomms.test.support.{visible_event_id}"
    group = f"diddicomms-test-{visible_event_id}"
    redis = create_redis()

    def stream_fields(*, event_id, version: int, visibility: str) -> dict[str, str]:
        # This is the Redis shape emitted by DiddiSupport RedisStreamPublisher.
        envelope = {
            "event_id": str(event_id),
            "event_type": "support.case.message.created.v1",
            "aggregate_id": str(case_id),
            "aggregate_version": version,
            "occurred_at": "2026-10-21T00:00:00+00:00",
            "payload": {
                "case_id": str(case_id),
                "message_id": str(uuid4()),
                "visibility": visibility,
            },
        }
        return {"event": json.dumps(envelope, separators=(",", ":"))}

    try:
        async with async_session_factory() as session:
            session.add(
                ConversationModel(
                    id=conversation_id,
                    conversation_type="support",
                    owner_service="diddisupport",
                    task_type="support_case",
                    task_id=case_id,
                    state="open",
                )
            )
            session.add(
                SupportCaseModel(
                    id=case_id,
                    external_case_id=case_id,
                    conversation_id=conversation_id,
                    requester_user_id=uuid4(),
                    subject="canonical support stream test",
                    status="open",
                    priority="normal",
                    projection_status="pending",
                    support_version=1,
                )
            )
            await session.commit()

        consumer = RedisStreamConsumer(
            async_session_factory,
            redis,
            stream_name=stream,
            group_name=group,
            consumer_name="integration-consumer",
        )
        await consumer.ensure_group()

        visible_fields = stream_fields(event_id=visible_event_id, version=2, visibility="user_visible")
        await redis.xadd(stream, visible_fields)
        await redis.xadd(stream, visible_fields)
        await redis.xadd(
            stream,
            stream_fields(event_id=internal_event_id, version=3, visibility="internal_note"),
        )

        assert await consumer.read_once(block_ms=10) == 3

        async with async_session_factory() as session:
            processed_count = await session.scalar(
                select(func.count())
                .select_from(ProcessedEventModel)
                .where(ProcessedEventModel.event_id.in_([visible_event_id, internal_event_id]))
            )
            visible_notifications = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.causation_id == visible_event_id)
            )
            internal_notifications = await session.scalar(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.causation_id == internal_event_id)
            )
            case = await session.get(SupportCaseModel, case_id)

            assert processed_count == 2
            assert visible_notifications == 1
            assert internal_notifications == 0
            assert case is not None
            assert case.support_version == 3

        assert (await redis.xpending(stream, group))["pending"] == 0
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(ProcessedEventModel).where(
                    ProcessedEventModel.event_id.in_([visible_event_id, internal_event_id])
                )
            )
            await session.execute(
                delete(OutboxEventModel).where(
                    OutboxEventModel.causation_id.in_([visible_event_id, internal_event_id])
                )
            )
            await session.execute(delete(ConversationModel).where(ConversationModel.id == conversation_id))
            await session.commit()
        await redis.delete(stream)
        await redis.aclose()
