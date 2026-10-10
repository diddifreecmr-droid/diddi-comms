from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

DIDDICOMMS_EVENTS_STREAM = "diddicomms.events"
DIDDICOMMS_EVENTS_DLQ_STREAM = "diddicomms.events.dlq"


@dataclass(frozen=True)
class OutboxEventDraft:
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict = field(default_factory=dict)
    event_version: int = 1
    correlation_id: str | None = None
    causation_id: UUID | None = None

