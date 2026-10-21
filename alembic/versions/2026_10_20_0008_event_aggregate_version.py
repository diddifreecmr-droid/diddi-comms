"""event aggregate versions

Revision ID: 2026_10_20_0008
Revises: 2026_10_20_0007
Create Date: 2026-10-20 00:08:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2026_10_20_0008"
down_revision: str | None = "2026_10_20_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("aggregate_version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("outbox_events", "aggregate_version")
