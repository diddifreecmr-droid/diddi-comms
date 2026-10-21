from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.events.domain import OutboxEventDraft
from app_base.modules.events.infra.models import OutboxEventModel


class OutboxWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, draft: OutboxEventDraft) -> OutboxEventModel:
        event = OutboxEventModel(
            id=uuid4(),
            aggregate_type=draft.aggregate_type,
            aggregate_id=draft.aggregate_id,
            event_type=draft.event_type,
            event_version=draft.event_version,
            aggregate_version=draft.aggregate_version,
            payload=draft.payload,
            correlation_id=draft.correlation_id,
            causation_id=draft.causation_id,
        )
        self.session.add(event)
        return event
