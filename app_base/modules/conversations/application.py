from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app_base.core.metrics import increment
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
    MessageDeliveryRepository,
    MessageRepository,
    SupportCaseRepository,
)
from app_base.modules.events.application import OutboxWriter
from app_base.modules.events.domain import OutboxEventDraft
from app_base.modules.support.factory import diddisupport_read_client
from app_base.modules.support.read_client import DiddiSupportReadClient


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
                event_type="comms.conversation.created.v1",
                aggregate_version=context.version,
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


@dataclass(frozen=True)
class ReadCursorResult:
    conversation_id: UUID
    read_sequence: int


@dataclass(frozen=True)
class DeliveryReceiptResult:
    message_id: UUID
    conversation_id: UUID
    status: str
    changed: bool


class MessageDeliveryService:
    def __init__(self, session: AsyncSession) -> None:
        self.messages = MessageRepository(session)
        self.conversations = ConversationRepository(session)
        self.deliveries = MessageDeliveryRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def acknowledge(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID,
        recipient_user_id: UUID,
        status: str,
        request_id: str | None = None,
    ) -> DeliveryReceiptResult:
        message = await self.messages.find_by_id(message_id)
        if message is None or message.conversation_id != conversation_id:
            raise LookupError("MESSAGE_NOT_FOUND")
        delivery = await self.deliveries.find_for_recipient(
            message_id=message_id,
            recipient_user_id=recipient_user_id,
        )
        if delivery is None:
            raise PermissionError("ACTOR_NOT_MESSAGE_RECIPIENT")
        changed = self.deliveries.advance(delivery, status=status)
        if changed:
            if status == "delivered":  # noqa: SIM108 - literal branches keep manifest conformance discoverable.
                event_type = "comms.message.delivered.v1"
            else:
                event_type = "comms.message.read.v1"
            self.audit.add(
                AuditEventDraft(
                    actor_user_id=recipient_user_id,
                    action=f"message.{status}",
                    target_type="message",
                    target_id=str(message_id),
                    outcome="succeeded",
                    request_id=request_id,
                    safe_metadata={"conversation_id": str(conversation_id)},
                )
            )
            self.outbox.add(
                OutboxEventDraft(
                    aggregate_type="conversation",
                    aggregate_id=str(conversation_id),
                    event_type=event_type,
                    aggregate_version=message.sequence,
                    correlation_id=request_id,
                    payload={
                        "conversation_id": str(conversation_id),
                        "message_id": str(message_id),
                        "recipient_user_id": str(recipient_user_id),
                    },
                )
            )
            increment("diddicomms_delivery_receipts_total", {"status": status})
        return DeliveryReceiptResult(
            message_id=message_id,
            conversation_id=conversation_id,
            status=delivery.status,
            changed=changed,
        )


class MarkConversationReadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.conversations = ConversationRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)

    async def mark(
        self,
        *,
        conversation_id: UUID,
        actor_user_id: UUID,
        read_sequence: int,
        request_id: str | None = None,
    ) -> ReadCursorResult:
        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None:
            raise LookupError("CONVERSATION_NOT_FOUND")
        bounded_sequence = min(max(read_sequence, 0), int(conversation.last_sequence or 0))
        current_sequence = await self.conversations.mark_read(
            conversation_id=conversation_id,
            user_id=actor_user_id,
            read_sequence=bounded_sequence,
        )
        self.audit.add(
            AuditEventDraft(
                actor_user_id=actor_user_id,
                action="conversation.read_cursor_changed",
                target_type="conversation",
                target_id=str(conversation_id),
                outcome="succeeded",
                request_id=request_id,
                safe_metadata={"read_sequence": current_sequence},
            )
        )
        self.outbox.add(
            OutboxEventDraft(
                aggregate_type="conversation",
                aggregate_id=str(conversation_id),
                event_type="comms.conversation.read_cursor_changed.v1",
                aggregate_version=current_sequence,
                correlation_id=request_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "user_id": str(actor_user_id),
                    "read_sequence": current_sequence,
                },
            )
        )
        return ReadCursorResult(conversation_id=conversation_id, read_sequence=current_sequence)


class SendMessageService:
    max_body_length = 2000

    def __init__(
        self,
        session: AsyncSession,
        *,
        resolver_factory: ResolverFactory = resolver_for_owner,
        policy: ConversationAccessPolicy | None = None,
        support_client: DiddiSupportReadClient | None = None,
    ) -> None:
        self.session = session
        self.resolver_factory = resolver_factory
        self.policy = policy or ConversationAccessPolicy()
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.deliveries = MessageDeliveryRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)
        self.support_client = support_client

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

        conversation = await self.conversations.find_by_id(conversation_id)
        if conversation is None:
            raise LookupError("CONVERSATION_NOT_FOUND")
        existing = await self.messages.find_by_client_message(
            sender_user_id=actor_user_id,
            client_message_id=client_message_id,
        )
        if existing is not None and (existing.conversation_id != conversation_id or existing.body != body):
            raise ValueError("MESSAGE_IDEMPOTENCY_CONFLICT")

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
            case = await SupportCaseRepository(self.session).find_by_conversation(conversation.id)
            if case is None:
                raise LookupError("SUPPORT_CASE_NOT_FOUND")
            support_client = self.support_client or diddisupport_read_client()
            remote_message = await support_client.send_user_message(
                case_id=case.external_case_id,
                reporter_user_id=actor_user_id,
                body=body,
                idempotency_key=client_message_id,
                request_id=request_id,
            )
            if existing is not None:
                return SendMessageResult(message=existing, created=False)
            message = self.messages.add_message(
                conversation=conversation,
                sender_user_id=actor_user_id,
                client_message_id=client_message_id,
                body=body,
                message_id=remote_message.message_id,
            )
            participants = await self.conversations.participants_for(conversation.id)
            self.deliveries.add_recipients(message=message, participants=participants)
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
                    event_type="comms.support.message.created.v1",
                    aggregate_version=message.sequence,
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

        if existing is not None:
            return SendMessageResult(message=existing, created=False)

        message = self.messages.add_message(
            conversation=conversation,
            sender_user_id=actor_user_id,
            client_message_id=client_message_id,
            body=body,
        )
        participants = await self.conversations.participants_for(conversation.id)
        self.deliveries.add_recipients(message=message, participants=participants)
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
                event_type="comms.message.created.v1",
                aggregate_version=message.sequence,
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
        support_client: DiddiSupportReadClient | None = None,
    ) -> None:
        self.session = session
        self.resolver_factory = resolver_factory
        self.policy = policy or ConversationAccessPolicy()
        self.conversations = ConversationRepository(session)
        self.messages = MessageRepository(session)
        self.support_cases = SupportCaseRepository(session)
        self.audit = AuditRecorder(session)
        self.outbox = OutboxWriter(session)
        self.support_client = support_client

    async def open_case(
        self,
        *,
        requester_user_id: UUID,
        subject: str,
        priority: str = "normal",
        category: str = "general",
        origin_report_id: str | None = None,
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

        if task is None:
            raise ValueError("SUPPORT_RESOURCE_REFERENCE_REQUIRED")

        if not idempotency_key:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")

        support_client = self.support_client or diddisupport_read_client()
        remote_case = await support_client.create_case(
            origin_service=task.owner_service,
            resource_type=task.task_type,
            resource_id=task.task_id,
            origin_report_id=origin_report_id or idempotency_key,
            reporter_user_id=requester_user_id,
            category=category,
            subject=subject,
            priority=priority,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )

        remote_initial_message = None
        if initial_message and initial_message.strip():
            remote_initial_message = await support_client.send_user_message(
                case_id=remote_case.case_id,
                reporter_user_id=requester_user_id,
                body=initial_message.strip(),
                idempotency_key=f"{idempotency_key}:initial-message",
                request_id=request_id,
            )

        case_id = remote_case.case_id
        existing_case = await self.support_cases.find_by_id(case_id)
        if existing_case is not None:
            existing_conversation = await self.conversations.find_by_id(existing_case.conversation_id)
            if existing_conversation is None:
                raise RuntimeError("SUPPORT_PROJECTION_INCONSISTENT")
            return SupportCaseResult(case=existing_case, conversation=existing_conversation)

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
        if remote_initial_message is not None:
            self.messages.add_message(
                conversation=conversation,
                sender_user_id=requester_user_id,
                client_message_id=f"{idempotency_key}:initial-message",
                body=initial_message.strip(),
                message_id=remote_initial_message.message_id,
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
                event_type="comms.support.case_opened.v1",
                aggregate_version=1,
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
                event_type="comms.support.case_resolved.v1",
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
