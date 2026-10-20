"""call attempts

Revision ID: 2026_10_20_0005
Revises: 2026_10_11_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_10_20_0005"
down_revision: str | None = "2026_10_11_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "call_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), server_default="authorized", nullable=False),
        sa.Column("client_result", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("actor_user_id", "idempotency_key", name="uq_call_attempt_actor_idempotency"),
    )
    op.create_index("ix_call_attempts_conversation_created", "call_attempts", ["conversation_id", "created_at"])
    op.create_index("ix_call_attempts_outcome_created", "call_attempts", ["outcome", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_call_attempts_outcome_created", table_name="call_attempts")
    op.drop_index("ix_call_attempts_conversation_created", table_name="call_attempts")
    op.drop_table("call_attempts")
