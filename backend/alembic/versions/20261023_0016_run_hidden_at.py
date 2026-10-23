"""Agent Activity can be cleared: finished runs are hidden, their records kept

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-23 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("hidden_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("workflow_runs", "hidden_at")
