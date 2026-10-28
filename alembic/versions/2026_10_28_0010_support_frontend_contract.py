"""Add Support category and requester activity index.

Revision ID: 2026_10_28_0010
Revises: 2026_10_20_0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_10_28_0010"
down_revision: str | None = "2026_10_20_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "support_cases",
        sa.Column("category", sa.Text(), nullable=False, server_default="general"),
    )
    op.create_index(
        "ix_support_cases_requester_updated",
        "support_cases",
        ["requester_user_id", "updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_support_cases_requester_updated", table_name="support_cases")
    op.drop_column("support_cases", "category")
