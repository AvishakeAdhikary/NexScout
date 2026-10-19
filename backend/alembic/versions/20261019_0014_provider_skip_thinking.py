"""Providers: optionally skip a reasoning model's thinking (OpenAI-compatible servers)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("skip_thinking", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("provider_configs", "skip_thinking")
