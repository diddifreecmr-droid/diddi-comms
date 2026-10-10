from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.audit.infra.models import AuditEventModel


@dataclass(frozen=True)
class AuditEventDraft:
    action: str
    target_type: str
    outcome: str
    actor_user_id: UUID | None = None
    actor_service: str | None = None
    target_id: str | None = None
    reason_code: str | None = None
    request_id: str | None = None
    idempotency_key: str | None = None
    safe_metadata: dict = field(default_factory=dict)


class AuditRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, draft: AuditEventDraft) -> AuditEventModel:
        if draft.actor_user_id is None and draft.actor_service is None:
            raise ValueError("audit event requires actor_user_id or actor_service")
        event = AuditEventModel(
            id=uuid4(),
            actor_user_id=draft.actor_user_id,
            actor_service=draft.actor_service,
            action=draft.action,
            target_type=draft.target_type,
            target_id=draft.target_id,
            outcome=draft.outcome,
            reason_code=draft.reason_code,
            request_id=draft.request_id,
            idempotency_key=draft.idempotency_key,
            safe_metadata=draft.safe_metadata,
        )
        self.session.add(event)
        return event

