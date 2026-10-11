from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

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
from app_base.modules.conversations.infra.repositories import (
    ConversationRepository,
    MessageRepository,
    SupportCaseRepository,
)
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

        if conversation.conversation_type == "support":
            if ConversationState(conversation.state) not in self.policy.writable_states:
                raise PermissionError("CONVERSATION_STATE_FORBIDS_ACTION")
            if not await self.conversations.has_active_participant(
                conversation_id=conversation.id,
                user_id=actor_user_id,
            ):
                self.audit.add(
                    AuditEventDraft(
                        actor_user_id=actor_user_id,
                        action="support.message.create_denied",
                        target_type="conversation",
                        target_id=str(conversation.id),
                        outcome="denied",
                        reason_code="ACTOR_NOT_SUPPORT_PARTICIPANT",
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                    )
                )
                raise PermissionError("ACTOR_NOT_SUPPORT_PARTICIPANT")
            message = self.messages.add_message(
                conversation=conversation,
                sender_user_id=actor_user_id,
                client_message_id=client_message_id,
                body=body,
            )
            self.audit.add(
                AuditEventDraft(
                    actor_user_id=actor_user_id,
                    action="support.message.created",
                    target_type="message",
                    target_id=str(message.id),
                    outcome="succeeded",
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    safe_metadata={"conversation_id": str(conversation.id), "sequence": message.sequence},
                )
            )
            self.outbox.add(
                OutboxEventDraft(
                    aggregate_type="support_case",
                    aggregate_id=str(conversation.task_id),
                    event_type="comms.support.message.created",
                    correlation_id=request_id,
                    payload={
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                        "sequence": message.sequence,
                        "sender_user_id": str(actor_user_id),
                    },
                )
            )
            return SendMessageResult(message=message, created=True)

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


@dataclass(frozen=True)
class SupportCaseResult:
    case: object
    conversation: ConversationModel


class SupportCaseService:
    valid_priorities = {"low", "normal", "high", "urgent"}
    open_statuses = {"open", "assigned", "pending_user"}

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
        self.support_cases = SupportCaseRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def open_case(
        self,
        *,
        requester_user_id: UUID,
        subject: str,
        priority: str = "normal",
        initial_message: str | None = None,
        task: TaskReference | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> SupportCaseResult:
        subject = subject.strip()
        if not subject:
            raise ValueError("SUPPORT_SUBJECT_EMPTY")
        if priority not in self.valid_priorities:
            raise ValueError("SUPPORT_PRIORITY_INVALID")

        if task is not None:
            context = await self.resolver_factory(task.owner_service).get_task(task.task_type, task.task_id)
            decision = self.policy.decide(
                action=CommunicationAction.OPEN_CONVERSATION,
                actor_user_id=requester_user_id,
                context=context,
            )
            if not decision.allowed:
                raise PermissionError(decision.reason_code)

        case_id = uuid4()
        conversation_id = uuid4()
        conversation = ConversationModel(
            id=conversation_id,
            conversation_type="support",
            owner_service="support",
            task_type="case",
            task_id=case_id,
            state=ConversationState.ACTIVE.value,
            task_version=1,
        )
        self.session.add(conversation)
        self.conversations.add_participant(
            conversation_id=conversation_id,
            user_id=requester_user_id,
            role="requester",
        )
        case = self.support_cases.add_case(
            case_id=case_id,
            conversation_id=conversation_id,
            requester_user_id=requester_user_id,
            subject=subject,
            priority=priority,
            owner_service=task.owner_service if task else None,
            task_type=task.task_type if task else None,
            task_id=task.task_id if task else None,
        )
        if initial_message and initial_message.strip():
            self.messages.add_message(
                conversation=conversation,
                sender_user_id=requester_user_id,
                client_message_id=idempotency_key or f"support-case-{case_id}",
                body=initial_message.strip(),
            )
        self.audit.add(
            AuditEventDraft(
                actor_user_id=requester_user_id,
                action="support.case_opened",
                target_type="support_case",
                target_id=str(case_id),
                outcome="succeeded",
                request_id=request_id,
                idempotency_key=idempotency_key,
                safe_metadata={
                    "owner_service": task.owner_service if task else None,
                    "task_type": task.task_type if task else None,
                    "priority": priority,
                },
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="support_case",
                aggregate_id=str(case_id),
                event_type="comms.support.case_opened",
                correlation_id=request_id,
                payload={
                    "case_id": str(case_id),
                    "conversation_id": str(conversation_id),
                    "requester_user_id": str(requester_user_id),
                    "owner_service": task.owner_service if task else None,
                    "task_type": task.task_type if task else None,
                    "priority": priority,
                },
            )
        )
        return SupportCaseResult(case=case, conversation=conversation)

    async def assign_case(
        self,
        *,
        case_id: UUID,
        assignee_user_id: UUID,
        actor_service: str,
        request_id: str | None = None,
    ):
        case = await self.support_cases.find_by_id(case_id)
        if case is None:
            raise LookupError("SUPPORT_CASE_NOT_FOUND")
        if case.status == "resolved":
            raise ValueError("SUPPORT_CASE_RESOLVED")
        case.assigned_to_user_id = assignee_user_id
        case.assigned_by_service = actor_service
        case.status = "assigned"
        case.updated_at = datetime.now(UTC)
        if not await self.conversations.has_active_participant(
            conversation_id=case.conversation_id,
            user_id=assignee_user_id,
        ):
            self.conversations.add_participant(
                conversation_id=case.conversation_id,
                user_id=assignee_user_id,
                role="support_agent",
                permissions="support_agent",
            )
        self.audit.add(
            AuditEventDraft(
                actor_service=actor_service,
                action="support.case_assigned",
                target_type="support_case",
                target_id=str(case_id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"assignee_user_id": str(assignee_user_id)},
            )
        )
        return case

    async def update_priority(self, *, case_id: UUID, priority: str, actor_service: str, request_id: str | None = None):
        if priority not in self.valid_priorities:
            raise ValueError("SUPPORT_PRIORITY_INVALID")
        case = await self.support_cases.find_by_id(case_id)
        if case is None:
            raise LookupError("SUPPORT_CASE_NOT_FOUND")
        case.priority = priority
        case.updated_at = datetime.now(UTC)
        self.audit.add(
            AuditEventDraft(
                actor_service=actor_service,
                action="support.case_priority_updated",
                target_type="support_case",
                target_id=str(case_id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"priority": priority},
            )
        )
        return case

    async def resolve_case(
        self,
        *,
        case_id: UUID,
        actor_service: str,
        resolution_note: str | None = None,
        request_id: str | None = None,
    ):
        case = await self.support_cases.find_by_id(case_id)
        if case is None:
            raise LookupError("SUPPORT_CASE_NOT_FOUND")
        case.status = "resolved"
        case.resolved_by_service = actor_service
        case.resolution_note = resolution_note.strip() if resolution_note else None
        case.resolved_at = datetime.now(UTC)
        case.updated_at = case.resolved_at
        conversation = await self.conversations.find_by_id(case.conversation_id)
        if conversation is not None:
            conversation.state = ConversationState.CLOSED.value
            conversation.closed_at = case.resolved_at
            conversation.updated_at = case.resolved_at
        self.audit.add(
            AuditEventDraft(
                actor_service=actor_service,
                action="support.case_resolved",
                target_type="support_case",
                target_id=str(case_id),
                outcome="succeeded",
                request_id=request_id,
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="support_case",
                aggregate_id=str(case_id),
                event_type="comms.support.case_resolved",
                correlation_id=request_id,
                payload={"case_id": str(case_id)},
            )
        )
        return case

    async def send_agent_message(
        self,
        *,
        case_id: UUID,
        agent_user_id: UUID,
        client_message_id: str,
        body: str,
        actor_service: str,
        request_id: str | None = None,
    ) -> SendMessageResult:
        case = await self.support_cases.find_by_id(case_id)
        if case is None:
            raise LookupError("SUPPORT_CASE_NOT_FOUND")
        if case.status == "resolved":
            raise ValueError("SUPPORT_CASE_RESOLVED")
        if case.assigned_to_user_id != agent_user_id:
            raise PermissionError("SUPPORT_CASE_NOT_ASSIGNED_TO_AGENT")
        result = await SendMessageService(self.session).send(
            conversation_id=case.conversation_id,
            actor_user_id=agent_user_id,
            client_message_id=client_message_id,
            body=body,
            request_id=request_id,
        )
        self.audit.add(
            AuditEventDraft(
                actor_service=actor_service,
                action="support.agent_message_sent",
                target_type="support_case",
                target_id=str(case_id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"agent_user_id": str(agent_user_id), "message_id": str(result.message.id)},
            )
        )
        return result
