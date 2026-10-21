from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.auth_deps import DelegatedOperator
from app_base.modules.audit.application import AuditEventDraft, AuditRecorder
from app_base.modules.context.domain import TaskReference
from app_base.modules.context.infra.factory import resolver_for_owner
from app_base.modules.conversations.application import ResolverFactory
from app_base.modules.conversations.domain import ConversationState
from app_base.modules.conversations.infra.models import ConversationModel, MessageModel
from app_base.modules.conversations.infra.repositories import (
    ConversationRepository,
    MessageDeliveryRepository,
    MessageRepository,
)
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft


@dataclass(frozen=True)
class BackofficeConversationResult:
    conversation: ConversationModel
    created: bool


@dataclass(frozen=True)
class BackofficeMessageResult:
    message: MessageModel
    created: bool


class BackofficeConversationService:
    max_body_length = 2000

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver_factory: ResolverFactory = resolver_for_owner,
    ) -> None:
        self.session = session
        self.resolver_factory = resolver_factory
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.deliveries = MessageDeliveryRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def ensure_conversation(
        self,
        *,
        task: TaskReference,
        operator: DelegatedOperator,
        idempotency_key: str,
    ) -> BackofficeConversationResult:
        context = await self.resolver_factory(task.owner_service).get_task(task.task_type, task.task_id)
        existing = await self.conversations.find_by_task(context.task)
        if existing is not None:
            self._audit(
                operator,
                action="backoffice.conversation.reused",
                target_type="conversation",
                target_id=str(existing.id),
                idempotency_key=idempotency_key,
                metadata={"owner_service": task.owner_service, "task_type": task.task_type},
            )
            return BackofficeConversationResult(conversation=existing, created=False)

        draft = self.conversations.add_task_conversation(context)
        self._audit(
            operator,
            action="backoffice.conversation.opened",
            target_type="conversation",
            target_id=str(draft.conversation.id),
            idempotency_key=idempotency_key,
            metadata={"owner_service": task.owner_service, "task_type": task.task_type},
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(draft.conversation.id),
                event_type="comms.conversation.created.v1",
                aggregate_version=context.version,
                correlation_id=operator.request_id,
                payload={
                    "conversation_id": str(draft.conversation.id),
                    "owner_service": task.owner_service,
                    "task_type": task.task_type,
                },
            )
        )
        return BackofficeConversationResult(conversation=draft.conversation, created=True)

    async def list_messages(
        self,
        *,
        conversation_id: UUID,
        operator: DelegatedOperator,
        after_sequence: int,
        limit: int,
    ) -> list[MessageModel]:
        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None or conversation.conversation_type != "task":
            raise LookupError("CONVERSATION_NOT_FOUND")
        messages = await self.messages.list_after(
            conversation_id=conversation_id,
            after_sequence=max(after_sequence, 0),
            limit=min(max(limit, 1), 200),
        )
        self._audit(
            operator,
            action="backoffice.messages.read",
            target_type="conversation",
            target_id=str(conversation_id),
            metadata={"message_count": len(messages)},
        )
        return messages

    async def send_message(
        self,
        *,
        conversation_id: UUID,
        operator: DelegatedOperator,
        client_message_id: str,
        body: str,
        idempotency_key: str,
    ) -> BackofficeMessageResult:
        body = body.strip()
        if not body:
            raise ValueError("MESSAGE_BODY_EMPTY")
        if len(body) > self.max_body_length:
            raise ValueError("MESSAGE_BODY_TOO_LONG")

        existing = await self.messages.find_by_client_message(
            sender_user_id=operator.operator_user_id,
            client_message_id=client_message_id,
        )
        if existing is not None:
            if existing.conversation_id != conversation_id or existing.body != body:
                raise ValueError("MESSAGE_IDEMPOTENCY_CONFLICT")
            return BackofficeMessageResult(message=existing, created=False)

        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None or conversation.conversation_type != "task":
            raise LookupError("CONVERSATION_NOT_FOUND")
        if ConversationState(conversation.state) not in {ConversationState.ACTIVE, ConversationState.GRACE}:
            raise PermissionError("CONVERSATION_STATE_FORBIDS_ACTION")

        message = self.messages.add_message(
            conversation=conversation,
            sender_user_id=operator.operator_user_id,
            client_message_id=client_message_id,
            body=body,
        )
        participants = await self.conversations.participants_for(conversation.id)
        self.deliveries.add_recipients(message=message, participants=participants)
        self._audit(
            operator,
            action="backoffice.message.created",
            target_type="message",
            target_id=str(message.id),
            idempotency_key=idempotency_key,
            metadata={"conversation_id": str(conversation_id), "sequence": message.sequence},
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(conversation_id),
                event_type="comms.message.created.v1",
                aggregate_version=message.sequence,
                correlation_id=operator.request_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "message_id": str(message.id),
                    "sequence": message.sequence,
                    "sender_user_id": str(operator.operator_user_id),
                    "author_type": "backoffice_operator",
                    "owner_service": conversation.owner_service,
                    "task_type": conversation.task_type,
                },
            )
        )
        return BackofficeMessageResult(message=message, created=True)

    def _audit(
        self,
        operator: DelegatedOperator,
        *,
        action: str,
        target_type: str,
        target_id: str,
        idempotency_key: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.audit.add(
            AuditEventDraft(
                actor_user_id=operator.operator_user_id,
                actor_service=operator.service.subject,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome="succeeded",
                request_id=operator.request_id,
                idempotency_key=idempotency_key,
                safe_metadata={
                    "client_id": operator.service.client_id,
                    "reason": operator.reason,
                    **(metadata or {}),
                },
            )
        )
