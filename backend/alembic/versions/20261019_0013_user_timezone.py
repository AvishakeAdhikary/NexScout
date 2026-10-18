"""User time zone: date-only reminders fall due on the user's own calendar day

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19 04:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from nexscout.infrastructure.db.rls import SYSTEM_ROLE, grant_system

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
    )
    # The worker's sweep reads each user's zone and nothing else about them.
    grant_system("users", "SELECT (id, timezone)")


def downgrade() -> None:
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SYSTEM_ROLE}') "
        f"THEN EXECUTE 'REVOKE SELECT (id, timezone) ON users FROM {SYSTEM_ROLE}'; END IF; END $$"
    )
    op.drop_column("users", "timezone")
