from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app_base.modules.context.domain import CommunicationContext, TaskReference
from app_base.modules.conversations.domain import ConversationState
from app_base.modules.conversations.infra.models import (
    CallAttemptModel,
    ConversationModel,
    ConversationParticipantModel,
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
    ) -> MessageModel:
        sequence = int(conversation.last_sequence or 0) + 1
        conversation.last_sequence = sequence
        message = MessageModel(
            id=uuid4(),
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


class SupportCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_id(self, case_id: UUID) -> SupportCaseModel | None:
        return await self.session.get(SupportCaseModel, case_id)

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

    def add_case(
        self,
        *,
        case_id: UUID,
        conversation_id: UUID,
        requester_user_id: UUID,
        subject: str,
        priority: str,
        owner_service: str | None = None,
        task_type: str | None = None,
        task_id: UUID | None = None,
    ) -> SupportCaseModel:
        case = SupportCaseModel(
            id=case_id,
            conversation_id=conversation_id,
            requester_user_id=requester_user_id,
            owner_service=owner_service,
            task_type=task_type,
            task_id=task_id,
            subject=subject,
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
