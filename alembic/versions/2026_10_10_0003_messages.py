"""messages and message deliveries

Revision ID: 2026_10_10_0003
Revises: 2026_10_10_0002
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2026_10_10_0003"
down_revision = "2026_10_10_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sender_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_message_id", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("moderation_status", sa.Text(), nullable=False, server_default="accepted"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_messages_conversation_sequence"),
        sa.UniqueConstraint("sender_user_id", "client_message_id", name="uq_messages_sender_client_message"),
    )
    op.create_index("ix_messages_conversation_sequence", "messages", ["conversation_id", "sequence"])

    op.create_table(
        "message_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_error_code", sa.Text(), nullable=True),
        sa.UniqueConstraint("message_id", "participant_id", "channel", name="uq_message_delivery_channel"),
    )
    op.create_index("ix_message_deliveries_status", "message_deliveries", ["status", "attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_message_deliveries_status", table_name="message_deliveries")
    op.drop_table("message_deliveries")
    op.drop_index("ix_messages_conversation_sequence", table_name="messages")
    op.drop_table("messages")
