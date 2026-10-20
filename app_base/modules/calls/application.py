from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.context.domain import TaskReference
from app_base.modules.context.infra.factory import resolver_for_owner
from app_base.modules.conversations.domain import (
    CommunicationAction,
    ConversationAccessPolicy,
    ConversationAccessSnapshot,
    ConversationState,
)
from app_base.modules.conversations.infra.models import CallAttemptModel
from app_base.modules.conversations.infra.repositories import CallAttemptRepository, ConversationRepository
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft


@dataclass(frozen=True)
class CallAttemptResult:
    attempt: CallAttemptModel
    target_phone_e164: str
    created: bool


class CreateCallAttemptService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.attempts = CallAttemptRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)
        self.policy = ConversationAccessPolicy()

    async def create(
        self,
        *,
        conversation_id: UUID,
        actor_user_id: UUID,
        target_user_id: UUID,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> CallAttemptResult:
        existing = await self.attempts.find_by_idempotency(
            actor_user_id=actor_user_id, idempotency_key=idempotency_key
        )
        if existing is not None:
            if existing.conversation_id != conversation_id or existing.target_user_id != target_user_id:
                raise ValueError("CALL_IDEMPOTENCY_CONFLICT")
            existing_conversation = await self.conversations.find_by_id(conversation_id)
            if existing_conversation is None:
                raise LookupError("CONVERSATION_NOT_FOUND")
            existing_task = TaskReference(
                owner_service=existing_conversation.owner_service,
                task_type=existing_conversation.task_type,
                task_id=existing_conversation.task_id,
            )
            existing_context = await resolver_for_owner(existing_task.owner_service).get_task(
                existing_task.task_type, existing_task.task_id
            )
            existing_target = next(
                (participant for participant in existing_context.participants if participant.user_id == target_user_id),
                None,
            )
            if existing_target is None or not existing_target.phone_e164:
                raise ValueError("CALL_TARGET_NUMBER_UNAVAILABLE")
            return CallAttemptResult(existing, existing_target.phone_e164, False)

        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None:
            raise LookupError("CONVERSATION_NOT_FOUND")
        if conversation.conversation_type != "task":
            raise PermissionError("CALL_NOT_ALLOWED_FOR_CONVERSATION_TYPE")

        task = TaskReference(
            owner_service=conversation.owner_service,
            task_type=conversation.task_type,
            task_id=conversation.task_id,
        )
        context = await resolver_for_owner(task.owner_service).get_task(task.task_type, task.task_id)
        decision = self.policy.decide(
            action=CommunicationAction.CALL,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            context=context,
            conversation=ConversationAccessSnapshot(
                task=task,
                state=ConversationState(conversation.state),
                closes_at=conversation.closes_at,
            ),
        )
        if not decision.allowed:
            self.audit.add(
                AuditEventDraft(
                    actor_user_id=actor_user_id,
                    action="call_attempt.denied",
                    target_type="conversation",
                    target_id=str(conversation_id),
                    outcome="denied",
                    reason_code=decision.reason_code,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
            )
            raise PermissionError(decision.reason_code)

        target = next(
            (participant for participant in context.participants if participant.user_id == target_user_id),
            None,
        )
        if target is None or not target.phone_e164:
            raise ValueError("CALL_TARGET_NUMBER_UNAVAILABLE")

        attempt = CallAttemptModel(
            id=uuid4(),
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            idempotency_key=idempotency_key,
            outcome="authorized",
            request_id=request_id,
        )
        self.session.add(attempt)
        self.audit.add(
            AuditEventDraft(
                actor_user_id=actor_user_id,
                action="call_attempt.created",
                target_type="call_attempt",
                target_id=str(attempt.id),
                outcome="succeeded",
                request_id=request_id,
                idempotency_key=idempotency_key,
                safe_metadata={"conversation_id": str(conversation_id), "target_user_id": str(target_user_id)},
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="call_attempt",
                aggregate_id=str(attempt.id),
                event_type="comms.call_attempt.created.v1",
                correlation_id=request_id,
                payload={
                    "call_attempt_id": str(attempt.id),
                    "conversation_id": str(conversation_id),
                    "actor_user_id": str(actor_user_id),
                    "target_user_id": str(target_user_id),
                },
            )
        )
        return CallAttemptResult(attempt, target.phone_e164, True)


class RecordCallClientResultService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.attempts = CallAttemptRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def record(self, *, attempt_id: UUID, actor_user_id: UUID, result: str, request_id: str | None = None):
        attempt = await self.session.get(CallAttemptModel, attempt_id)
        if attempt is None:
            raise LookupError("CALL_ATTEMPT_NOT_FOUND")
        if attempt.actor_user_id != actor_user_id:
            raise PermissionError("CALL_ATTEMPT_ACTOR_FORBIDDEN")
        if result not in {"started", "cancelled", "failed", "unknown"}:
            raise ValueError("CALL_CLIENT_RESULT_INVALID")
        attempt.client_result = result
        attempt.outcome = result
        attempt.updated_at = datetime.now(UTC)
        self.audit.add(
            AuditEventDraft(
                actor_user_id=actor_user_id,
                action="call_attempt.client_result_recorded",
                target_type="call_attempt",
                target_id=str(attempt.id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"client_result": result},
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="call_attempt",
                aggregate_id=str(attempt.id),
                event_type="comms.call_attempt.client_result_recorded.v1",
                correlation_id=request_id,
                payload={"call_attempt_id": str(attempt.id), "client_result": result},
            )
        )
        return attempt
