from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app_base.core.database import Base


class ConversationModel(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("owner_service", "task_type", "task_id", name="uq_conversation_task_reference"),
        Index("ix_conversations_task_reference", "owner_service", "task_type", "task_id"),
        Index("ix_conversations_state_closes_at", "state", "closes_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    conversation_type: Mapped[str] = mapped_column(Text, nullable=False)
    owner_service: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    task_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConversationParticipantModel(Base):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conversation_participant_user"),
        Index("ix_conversation_participants_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    permissions: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notification_preference: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")


class MessageModel(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        UniqueConstraint("sender_user_id", "client_message_id", name="uq_messages_sender_client_message"),
        Index("ix_messages_conversation_sequence", "conversation_id", "sequence"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    sender_user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    client_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    moderation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="accepted")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MessageDeliveryModel(Base):
    __tablename__ = "message_deliveries"
    __table_args__ = (
        UniqueConstraint("message_id", "participant_id", "channel", name="uq_message_delivery_channel"),
        Index("ix_message_deliveries_status", "status", "attempted_at"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    message_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversation_participants.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)


class SupportCaseModel(Base):
    __tablename__ = "support_cases"
    __table_args__ = (
        Index("ix_support_cases_status_priority", "status", "priority"),
        Index("ix_support_cases_requester", "requester_user_id"),
        Index("ix_support_cases_assignee", "assigned_to_user_id"),
        Index("ix_support_cases_task_reference", "owner_service", "task_type", "task_id"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    requester_user_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    owner_service: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    priority: Mapped[str] = mapped_column(Text, nullable=False, server_default="normal")
    assigned_to_user_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    assigned_by_service: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_service: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
