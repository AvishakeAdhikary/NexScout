"""M1 baseline: users, sessions, login attempts, candidate cases, audit events.

Revision ID: 0001
Revises:
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from nexscout.infrastructure.db.rls import disable_owner_rls, enable_owner_rls, grant_app

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else sa.func.now(),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("email = lower(email)", name="email_lowercase"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        _ts("created_at"),
    )
    op.create_index(
        "ix_login_attempts_email_created", "login_attempts", ["email_hash", "created_at"]
    )
    op.create_index("ix_login_attempts_ip_created", "login_attempts", ["ip", "created_at"])

    op.create_table(
        "candidate_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("career_path", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_candidate_cases_owner_name"),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_candidate_cases_id_owner"),
        sa.CheckConstraint(
            "career_path IN ('undecided','phd','employment','both')", name="career_path_valid"
        ),
        sa.CheckConstraint("status IN ('active','paused','archived')", name="status_valid"),
    )
    op.create_index("ix_candidate_cases_owner", "candidate_cases", ["owner_user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(80), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("meta", pg.JSONB(), nullable=False),
        sa.Column("ip", pg.INET(), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        _ts("created_at"),
    )
    op.create_index(
        "ix_audit_events_actor_created", "audit_events", ["actor_user_id", "created_at"]
    )

    # --- tenant isolation + least-privilege grants for the runtime role
    enable_owner_rls("candidate_cases")
    grant_app("users")
    grant_app("sessions")
    grant_app("login_attempts", "SELECT, INSERT, DELETE")
    grant_app("candidate_cases")
    grant_app("audit_events", "INSERT")  # app can write but never read the audit trail


def downgrade() -> None:
    disable_owner_rls("candidate_cases")
    op.drop_table("audit_events")
    op.drop_table("candidate_cases")
    op.drop_table("login_attempts")
    op.drop_table("sessions")
    op.drop_table("users")
