"""conversation task references and participants

Revision ID: 2026_10_10_0002
Revises: 2026_10_09_0001
Create Date: 2026-10-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "2026_10_10_0002"
down_revision = "2026_10_09_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_type", sa.Text(), nullable=False),
        sa.Column("owner_service", sa.Text(), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_service", "task_type", "task_id", name="uq_conversation_task_reference"),
    )
    op.create_index(
        "ix_conversations_task_reference",
        "conversations",
        ["owner_service", "task_type", "task_id"],
    )
    op.create_index("ix_conversations_state_closes_at", "conversations", ["state", "closes_at"])

    op.create_table(
        "conversation_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("permissions", sa.Text(), nullable=False, server_default="member"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notification_preference", sa.Text(), nullable=False, server_default="default"),
        sa.UniqueConstraint("conversation_id", "user_id", name="uq_conversation_participant_user"),
    )
    op.create_index("ix_conversation_participants_user", "conversation_participants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_participants_user", table_name="conversation_participants")
    op.drop_table("conversation_participants")
    op.drop_index("ix_conversations_state_closes_at", table_name="conversations")
    op.drop_index("ix_conversations_task_reference", table_name="conversations")
    op.drop_table("conversations")

