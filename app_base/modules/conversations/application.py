from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.context.domain import CommunicationContext, ExternalName, TaskReference
from app_base.modules.context.infra.factory import resolver_for_owner
from app_base.modules.conversations.domain import (
    AccessDecision,
    CommunicationAction,
    ConversationAccessPolicy,
    ConversationAccessSnapshot,
    ConversationState,
)
from app_base.modules.conversations.infra.models import ConversationModel, MessageModel
from app_base.modules.conversations.infra.repositories import ConversationRepository, MessageRepository
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft


class TaskResolver(Protocol):
    async def get_task(self, task_type: ExternalName, task_id: UUID) -> CommunicationContext:
        pass


ResolverFactory = Callable[[str], TaskResolver]


@dataclass(frozen=True)
class CommunicationGateRequest:
    task: TaskReference
    action: CommunicationAction
    actor_user_id: UUID
    target_user_id: UUID | None = None
    conversation: ConversationAccessSnapshot | None = None


class TaskCommunicationGate:
    def __init__(
        self,
        *,
        resolver_factory: ResolverFactory = resolver_for_owner,
        policy: ConversationAccessPolicy | None = None,
    ) -> None:
        self.resolver_factory = resolver_factory
        self.policy = policy or ConversationAccessPolicy()

    async def decide(self, request: CommunicationGateRequest) -> AccessDecision:
        resolver = self.resolver_factory(request.task.owner_service)
        context = await resolver.get_task(request.task.task_type, request.task.task_id)
        return self.policy.decide(
            action=request.action,
            actor_user_id=request.actor_user_id,
            target_user_id=request.target_user_id,
            context=context,
            conversation=request.conversation,
        )


@dataclass(frozen=True)
class EnsureTaskConversationResult:
    conversation: ConversationModel
    created: bool
    context: CommunicationContext


class EnsureTaskConversationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver_factory: ResolverFactory = resolver_for_owner,
        policy: ConversationAccessPolicy | None = None,
    ) -> None:
        self.session = session
        self.resolver_factory = resolver_factory
        self.policy = policy or ConversationAccessPolicy()
        self.conversations = ConversationRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def ensure(
        self,
        *,
        task: TaskReference,
        actor_user_id: UUID,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> EnsureTaskConversationResult:
        resolver = self.resolver_factory(task.owner_service)
        context = await resolver.get_task(task.task_type, task.task_id)
        decision = self.policy.decide(
            action=CommunicationAction.OPEN_CONVERSATION,
            actor_user_id=actor_user_id,
            context=context,
        )
        if not decision.allowed:
            self.audit.add(
                AuditEventDraft(
                    actor_user_id=actor_user_id,
                    action="conversation.open_denied",
                    target_type="task",
                    target_id=_task_target(task),
                    outcome="denied",
                    reason_code=decision.reason_code,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    safe_metadata={"owner_service": task.owner_service, "task_type": task.task_type},
                )
            )
            raise PermissionError(decision.reason_code)

        existing = await self.conversations.find_by_task(context.task)
        if existing is not None:
            self.audit.add(
                AuditEventDraft(
                    actor_user_id=actor_user_id,
                    action="conversation.reused",
                    target_type="conversation",
                    target_id=str(existing.id),
                    outcome="succeeded",
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    safe_metadata={"owner_service": task.owner_service, "task_type": task.task_type},
                )
            )
            return EnsureTaskConversationResult(conversation=existing, created=False, context=context)

        draft = self.conversations.add_task_conversation(context)
        self.audit.add(
            AuditEventDraft(
                actor_user_id=actor_user_id,
                action="conversation.opened",
                target_type="conversation",
                target_id=str(draft.conversation.id),
                outcome="succeeded",
                request_id=request_id,
                idempotency_key=idempotency_key,
                safe_metadata={"owner_service": task.owner_service, "task_type": task.task_type},
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(draft.conversation.id),
                event_type="comms.conversation.opened",
                correlation_id=request_id,
                payload={
                    "conversation_id": str(draft.conversation.id),
                    "owner_service": task.owner_service,
                    "task_type": task.task_type,
                },
            )
        )
        return EnsureTaskConversationResult(conversation=draft.conversation, created=True, context=context)


def _task_target(task: TaskReference) -> str:
    return f"{task.owner_service}:{task.task_type}:{task.task_id}"


@dataclass(frozen=True)
class SendMessageResult:
    message: MessageModel
    created: bool


class SendMessageService:
    max_body_length = 2000

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver_factory: ResolverFactory = resolver_for_owner,
        policy: ConversationAccessPolicy | None = None,
    ) -> None:
        self.session = session
        self.resolver_factory = resolver_factory
        self.policy = policy or ConversationAccessPolicy()
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def send(
        self,
        *,
        conversation_id: UUID,
        actor_user_id: UUID,
        client_message_id: str,
        body: str,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> SendMessageResult:
        body = body.strip()
        if not body:
            raise ValueError("MESSAGE_BODY_EMPTY")
        if len(body) > self.max_body_length:
            raise ValueError("MESSAGE_BODY_TOO_LONG")

        existing = await self.messages.find_by_client_message(
            sender_user_id=actor_user_id,
            client_message_id=client_message_id,
        )
        if existing is not None:
            return SendMessageResult(message=existing, created=False)

        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None:
            raise LookupError("CONVERSATION_NOT_FOUND")

        task = TaskReference(
            owner_service=conversation.owner_service,
            task_type=conversation.task_type,
            task_id=conversation.task_id,
        )
        context = await self.resolver_factory(task.owner_service).get_task(task.task_type, task.task_id)
        decision = self.policy.decide(
            action=CommunicationAction.MESSAGE,
            actor_user_id=actor_user_id,
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
                    action="message.create_denied",
                    target_type="conversation",
                    target_id=str(conversation.id),
                    outcome="denied",
                    reason_code=decision.reason_code,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    safe_metadata={"owner_service": task.owner_service, "task_type": task.task_type},
                )
            )
            raise PermissionError(decision.reason_code)

        message = self.messages.add_message(
            conversation=conversation,
            sender_user_id=actor_user_id,
            client_message_id=client_message_id,
            body=body,
        )
        self.audit.add(
            AuditEventDraft(
                actor_user_id=actor_user_id,
                action="message.created",
                target_type="message",
                target_id=str(message.id),
                outcome="succeeded",
                request_id=request_id,
                idempotency_key=idempotency_key,
                safe_metadata={
                    "conversation_id": str(conversation.id),
                    "owner_service": task.owner_service,
                    "task_type": task.task_type,
                    "sequence": message.sequence,
                },
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(conversation.id),
                event_type="comms.message.created",
                correlation_id=request_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "sequence": message.sequence,
                    "sender_user_id": str(actor_user_id),
                    "owner_service": task.owner_service,
                    "task_type": task.task_type,
                },
            )
        )
        return SendMessageResult(message=message, created=True)
