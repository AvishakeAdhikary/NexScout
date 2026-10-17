"""M10: let the worker's maintenance sweep enforce retention (delete-only grants)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-17 10:50:39.335846
"""

from collections.abc import Sequence

from alembic import op

from nexscout.infrastructure.db.rls import SYSTEM_ROLE

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RETENTION = ("workflow_events", "audit_events", "sessions", "login_attempts", "notifications")


def _grant(sql: str) -> None:
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{SYSTEM_ROLE}') "
        f"THEN EXECUTE '{sql}'; END IF; END $$"
    )


def upgrade() -> None:
    for table in RETENTION:
        _grant(f"GRANT SELECT, DELETE ON {table} TO {SYSTEM_ROLE}")


def downgrade() -> None:
    for table in RETENTION:
        _grant(f"REVOKE DELETE ON {table} FROM {SYSTEM_ROLE}")
