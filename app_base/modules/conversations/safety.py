from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.conversations.infra.models import ConversationMuteModel, MessageAbuseReportModel
from app_base.modules.conversations.infra.repositories import ConversationRepository, MessageRepository
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft


@dataclass(frozen=True)
class AbuseReportResult:
    report: MessageAbuseReportModel
    created: bool


class ConversationSafetyService:
    categories = {"harassment", "spam", "unsafe", "fraud", "other"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def set_muted(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        muted: bool,
        request_id: str | None = None,
    ) -> ConversationMuteModel:
        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None:
            raise LookupError("CONVERSATION_NOT_FOUND")
        if not await self.conversations.has_active_participant(conversation_id=conversation_id, user_id=user_id):
            raise PermissionError("ACTOR_NOT_CONVERSATION_PARTICIPANT")
        result = await self.session.execute(
            select(ConversationMuteModel).where(
                ConversationMuteModel.conversation_id == conversation_id,
                ConversationMuteModel.user_id == user_id,
            )
        )
        preference = result.scalar_one_or_none()
        if preference is None:
            preference = ConversationMuteModel(
                id=uuid4(),
                conversation_id=conversation_id,
                user_id=user_id,
                muted=muted,
            )
            self.session.add(preference)
        else:
            preference.muted = muted
            preference.updated_at = datetime.now(UTC)
        self.audit.add(
            AuditEventDraft(
                actor_user_id=user_id,
                action="conversation.mute_changed",
                target_type="conversation",
                target_id=str(conversation_id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"muted": muted},
            )
        )
        return preference

    async def report_message(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID,
        reporter_user_id: UUID,
        category: str,
        details: str | None,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> AbuseReportResult:
        if category not in self.categories:
            raise ValueError("ABUSE_CATEGORY_INVALID")
        if not await self.conversations.has_active_participant(
            conversation_id=conversation_id,
            user_id=reporter_user_id,
        ):
            raise PermissionError("ACTOR_NOT_CONVERSATION_PARTICIPANT")
        message = await self.messages.find_by_id(message_id)
        if message is None or message.conversation_id != conversation_id:
            raise LookupError("MESSAGE_NOT_FOUND")
        result = await self.session.execute(
            select(MessageAbuseReportModel).where(
                MessageAbuseReportModel.reporter_user_id == reporter_user_id,
                MessageAbuseReportModel.idempotency_key == idempotency_key,
            )
        )
        existing = result.scalar_one_or_none()
        normalized_details = details.strip() if details and details.strip() else None
        if existing is not None:
            if (
                existing.message_id != message_id
                or existing.category != category
                or existing.details != normalized_details
            ):
                raise ValueError("ABUSE_REPORT_IDEMPOTENCY_CONFLICT")
            return AbuseReportResult(report=existing, created=False)

        report = MessageAbuseReportModel(
            id=uuid4(),
            message_id=message_id,
            conversation_id=conversation_id,
            reporter_user_id=reporter_user_id,
            idempotency_key=idempotency_key,
            category=category,
            details=normalized_details,
            status="open",
        )
        self.session.add(report)
        self.audit.add(
            AuditEventDraft(
                actor_user_id=reporter_user_id,
                action="message.abuse_reported",
                target_type="message",
                target_id=str(message_id),
                outcome="succeeded",
                request_id=request_id,
                idempotency_key=idempotency_key,
                safe_metadata={"conversation_id": str(conversation_id), "category": category},
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(conversation_id),
                event_type="comms.message.abuse_reported.v1",
                aggregate_version=message.sequence,
                correlation_id=request_id,
                payload={
                    "report_id": str(report.id),
                    "conversation_id": str(conversation_id),
                    "message_id": str(message_id),
                    "reporter_user_id": str(reporter_user_id),
                    "category": category,
                },
            )
        )
        return AbuseReportResult(report=report, created=True)
