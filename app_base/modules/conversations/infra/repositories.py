from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.context.domain import CommunicationContext, TaskReference
from app_base.modules.conversations.domain import ConversationState
from app_base.modules.conversations.infra.models import (
    CallAttemptModel,
    ConversationModel,
    ConversationParticipantModel,
    MessageDeliveryModel,
    MessageModel,
    SupportCaseModel,
)


@dataclass(frozen=True)
class ConversationDraft:
    conversation: ConversationModel
    participants: list[ConversationParticipantModel]


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_task(self, task: TaskReference) -> ConversationModel | None:
        result = await self.session.execute(
            select(ConversationModel).where(
                ConversationModel.owner_service == task.owner_service,
                ConversationModel.task_type == task.task_type,
                ConversationModel.task_id == task.task_id,
            )
        )
        return result.scalar_one_or_none()

    def add_task_conversation(
        self,
        context: CommunicationContext,
        *,
        conversation_id: UUID | None = None,
        state: ConversationState = ConversationState.ACTIVE,
    ) -> ConversationDraft:
        draft = build_task_conversation(context, conversation_id=conversation_id, state=state)
        self.session.add(draft.conversation)
        for participant in draft.participants:
            self.session.add(participant)
        return draft

    async def find_by_id(self, conversation_id: UUID) -> ConversationModel | None:
        return await self.session.get(ConversationModel, conversation_id)

    async def participants_for(self, conversation_id: UUID) -> list[ConversationParticipantModel]:
        result = await self.session.execute(
            select(ConversationParticipantModel).where(
                ConversationParticipantModel.conversation_id == conversation_id,
                ConversationParticipantModel.left_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def has_active_participant(self, *, conversation_id: UUID, user_id: UUID) -> bool:
        result = await self.session.execute(
            select(ConversationParticipantModel.id).where(
                ConversationParticipantModel.conversation_id == conversation_id,
                ConversationParticipantModel.user_id == user_id,
                ConversationParticipantModel.left_at.is_(None),
            )
        )
        return result.scalar_one_or_none() is not None

    async def mark_read(self, *, conversation_id: UUID, user_id: UUID, read_sequence: int) -> int:
        result = await self.session.execute(
            select(ConversationParticipantModel).where(
                ConversationParticipantModel.conversation_id == conversation_id,
                ConversationParticipantModel.user_id == user_id,
                ConversationParticipantModel.left_at.is_(None),
            )
        )
        participant = result.scalar_one_or_none()
        if participant is None:
            raise LookupError("ACTOR_NOT_CONVERSATION_PARTICIPANT")
        participant.read_sequence = max(participant.read_sequence, read_sequence)
        return participant.read_sequence

    def add_participant(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        role: str,
        permissions: str = "member",
    ) -> ConversationParticipantModel:
        participant = ConversationParticipantModel(
            id=uuid4(),
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            permissions=permissions,
        )
        self.session.add(participant)
        return participant


def build_task_conversation(
    context: CommunicationContext,
    *,
    conversation_id: UUID | None = None,
    state: ConversationState = ConversationState.ACTIVE,
) -> ConversationDraft:
    resolved_conversation_id = conversation_id or uuid4()
    conversation = ConversationModel(
        id=resolved_conversation_id,
        conversation_type="task",
        owner_service=context.task.owner_service,
        task_type=context.task.task_type,
        task_id=context.task.task_id,
        state=state.value,
        task_version=context.version,
        closes_at=context.closes_at,
    )
    participants = [
        ConversationParticipantModel(
            id=uuid4(),
            conversation_id=resolved_conversation_id,
            user_id=participant.user_id,
            role=participant.role,
        )
        for participant in context.participants
    ]
    return ConversationDraft(conversation=conversation, participants=participants)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_client_message(self, *, sender_user_id: UUID, client_message_id: str) -> MessageModel | None:
        result = await self.session.execute(
            select(MessageModel).where(
                MessageModel.sender_user_id == sender_user_id,
                MessageModel.client_message_id == client_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def find_by_client_message_any_conversation(
        self, *, sender_user_id: UUID, client_message_id: str
    ) -> MessageModel | None:
        return await self.find_by_client_message(sender_user_id=sender_user_id, client_message_id=client_message_id)

    def add_message(
        self,
        *,
        conversation: ConversationModel,
        sender_user_id: UUID,
        client_message_id: str,
        body: str,
        message_id: UUID | None = None,
    ) -> MessageModel:
        sequence = int(conversation.last_sequence or 0) + 1
        conversation.last_sequence = sequence
        message = MessageModel(
            id=message_id or uuid4(),
            conversation_id=conversation.id,
            sequence=sequence,
            sender_user_id=sender_user_id,
            client_message_id=client_message_id,
            body=body,
            moderation_status="accepted",
        )
        self.session.add(message)
        return message

    async def list_after(self, *, conversation_id: UUID, after_sequence: int, limit: int = 100) -> list[MessageModel]:
        result = await self.session.execute(
            select(MessageModel)
            .where(
                MessageModel.conversation_id == conversation_id,
                MessageModel.sequence > after_sequence,
            )
            .order_by(MessageModel.sequence.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


class MessageDeliveryRepository:
    status_order = {"accepted": 0, "delivered": 1, "read": 2, "delivery_failed": 3}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_recipients(
        self,
        *,
        message: MessageModel,
        participants: list[ConversationParticipantModel],
    ) -> list[MessageDeliveryModel]:
        now = datetime.now(UTC)
        deliveries = []
        for participant in participants:
            if participant.user_id == message.sender_user_id:
                continue
            delivery = MessageDeliveryModel(
                id=uuid4(),
                message_id=message.id,
                participant_id=participant.id,
                channel="realtime",
                status="accepted",
                attempted_at=now,
            )
            self.session.add(delivery)
            deliveries.append(delivery)
        return deliveries

    async def find_for_recipient(
        self,
        *,
        message_id: UUID,
        recipient_user_id: UUID,
    ) -> MessageDeliveryModel | None:
        result = await self.session.execute(
            select(MessageDeliveryModel)
            .join(
                ConversationParticipantModel,
                ConversationParticipantModel.id == MessageDeliveryModel.participant_id,
            )
            .where(
                MessageDeliveryModel.message_id == message_id,
                ConversationParticipantModel.user_id == recipient_user_id,
                ConversationParticipantModel.left_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def find_by_id(self, message_id: UUID) -> MessageModel | None:
        return await self.session.get(MessageModel, message_id)

    def advance(self, delivery: MessageDeliveryModel, *, status: str) -> bool:
        if status not in {"delivered", "read"}:
            raise ValueError("DELIVERY_STATUS_INVALID")
        current_rank = self.status_order.get(delivery.status, -1)
        target_rank = self.status_order[status]
        if current_rank >= target_rank:
            return False
        now = datetime.now(UTC)
        delivery.status = status
        if status in {"delivered", "read"} and delivery.delivered_at is None:
            delivery.delivered_at = now
        if status == "read":
            delivery.read_at = now
        return True

    async def statuses_for_messages(self, message_ids: list[UUID]) -> dict[UUID, str]:
        if not message_ids:
            return {}
        result = await self.session.execute(
            select(MessageDeliveryModel.message_id, MessageDeliveryModel.status).where(
                MessageDeliveryModel.message_id.in_(message_ids)
            )
        )
        grouped: dict[UUID, list[str]] = {}
        for message_id, status in result.all():
            grouped.setdefault(message_id, []).append(status)
        return {message_id: self._aggregate_status(statuses) for message_id, statuses in grouped.items()}

    @staticmethod
    def _aggregate_status(statuses: list[str]) -> str:
        if not statuses:
            return "accepted"
        if any(status == "delivery_failed" for status in statuses):
            return "delivery_failed"
        if all(status == "read" for status in statuses):
            return "read"
        if all(status in {"delivered", "read"} for status in statuses):
            return "delivered"
        return "accepted"


class SupportCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_id(self, case_id: UUID) -> SupportCaseModel | None:
        return await self.session.get(SupportCaseModel, case_id)

    async def find_by_conversation(self, conversation_id: UUID) -> SupportCaseModel | None:
        result = await self.session.execute(
            select(SupportCaseModel).where(SupportCaseModel.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def list_cases(
        self,
        *,
        status: str | None = None,
        owner_service: str | None = None,
        limit: int = 100,
    ) -> list[SupportCaseModel]:
        statement = select(SupportCaseModel).order_by(SupportCaseModel.created_at.desc()).limit(limit)
        if status:
            statement = statement.where(SupportCaseModel.status == status)
        if owner_service:
            statement = statement.where(SupportCaseModel.owner_service == owner_service)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_for_requester(
        self,
        *,
        requester_user_id: UUID,
        status: str | None = None,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
        limit: int = 20,
    ) -> list[SupportCaseModel]:
        statement = select(SupportCaseModel).where(SupportCaseModel.requester_user_id == requester_user_id)
        if status:
            statement = statement.where(SupportCaseModel.status == status)
        if before_updated_at is not None and before_id is not None:
            statement = statement.where(
                or_(
                    SupportCaseModel.updated_at < before_updated_at,
                    and_(SupportCaseModel.updated_at == before_updated_at, SupportCaseModel.id < before_id),
                )
            )
        result = await self.session.execute(
            statement.order_by(SupportCaseModel.updated_at.desc(), SupportCaseModel.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    def add_case(
        self,
        *,
        case_id: UUID,
        conversation_id: UUID,
        requester_user_id: UUID,
        subject: str,
        category: str,
        priority: str,
        owner_service: str | None = None,
        task_type: str | None = None,
        task_id: UUID | None = None,
    ) -> SupportCaseModel:
        case = SupportCaseModel(
            id=case_id,
            external_case_id=case_id,
            projection_status="synced",
            conversation_id=conversation_id,
            requester_user_id=requester_user_id,
            owner_service=owner_service,
            task_type=task_type,
            task_id=task_id,
            subject=subject,
            category=category,
            status="open",
            priority=priority,
        )
        self.session.add(case)
        return case


class CallAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_idempotency(self, *, actor_user_id: UUID, idempotency_key: str) -> CallAttemptModel | None:
        result = await self.session.execute(
            select(CallAttemptModel).where(
                CallAttemptModel.actor_user_id == actor_user_id,
                CallAttemptModel.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()
