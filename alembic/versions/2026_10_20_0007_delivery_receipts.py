"""message delivery receipts

Revision ID: 2026_10_20_0007
Revises: 2026_10_20_0006
Create Date: 2026-10-20 00:07:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_10_20_0007"
down_revision: str | None = "2026_10_20_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("message_deliveries", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("message_deliveries", "read_at")
