"""support cases

Revision ID: 2026_10_11_0004
Revises: 2026_10_10_0003
Create Date: 2026-10-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_10_11_0004"
down_revision: str | None = "2026_10_10_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "support_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_service", sa.Text(), nullable=True),
        sa.Column("task_type", sa.Text(), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("priority", sa.Text(), server_default="normal", nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_by_service", sa.Text(), nullable=True),
        sa.Column("resolved_by_service", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id"),
    )
    op.create_index("ix_support_cases_assignee", "support_cases", ["assigned_to_user_id"])
    op.create_index("ix_support_cases_requester", "support_cases", ["requester_user_id"])
    op.create_index("ix_support_cases_status_priority", "support_cases", ["status", "priority"])
    op.create_index("ix_support_cases_task_reference", "support_cases", ["owner_service", "task_type", "task_id"])


def downgrade() -> None:
    op.drop_index("ix_support_cases_task_reference", table_name="support_cases")
    op.drop_index("ix_support_cases_status_priority", table_name="support_cases")
    op.drop_index("ix_support_cases_requester", table_name="support_cases")
    op.drop_index("ix_support_cases_assignee", table_name="support_cases")
    op.drop_table("support_cases")
