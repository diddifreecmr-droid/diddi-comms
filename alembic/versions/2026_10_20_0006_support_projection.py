"""support source-of-truth projection metadata

Revision ID: 2026_10_20_0006
Revises: 2026_10_20_0005
Create Date: 2026-10-20 00:06:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2026_10_20_0006"
down_revision: str | None = "2026_10_20_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("support_cases", sa.Column("external_case_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "support_cases",
        sa.Column("projection_status", sa.Text(), server_default="synced", nullable=False),
    )
    op.add_column("support_cases", sa.Column("support_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("support_cases", sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE support_cases SET external_case_id = id WHERE external_case_id IS NULL")
    op.alter_column("support_cases", "external_case_id", nullable=False)
    op.create_unique_constraint("uq_support_cases_external_case_id", "support_cases", ["external_case_id"])


def downgrade() -> None:
    op.drop_constraint("uq_support_cases_external_case_id", "support_cases", type_="unique")
    op.drop_column("support_cases", "last_reconciled_at")
    op.drop_column("support_cases", "support_version")
    op.drop_column("support_cases", "projection_status")
    op.drop_column("support_cases", "external_case_id")
