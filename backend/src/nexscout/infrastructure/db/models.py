"""ORM models. Owned tables carry owner_user_id and are protected by Postgres RLS (ADR-0003)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from nexscout.infrastructure.db.base import Base, IdMixin, TimestampMixin, new_id

# Tables listed here get RLS enabled+forced with the owner policy in migrations.
OWNED_TABLES: tuple[str, ...] = ("candidate_cases",)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)


class AuthSession(IdMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))


class LoginAttempt(Base):
    """Durable login-attempt log for rate limiting across API replicas."""

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET)
    succeeded: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_login_attempts_email_created", "email_hash", "created_at"),
        Index("ix_login_attempts_ip_created", "ip", "created_at"),
    )


class CandidateCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "candidate_cases"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    career_path: Mapped[str] = mapped_column(String(20), nullable=False, default="undecided")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_candidate_cases_owner_name"),
        # Target for composite FKs so child rows can never reference another user's case.
        UniqueConstraint("id", "owner_user_id", name="uq_candidate_cases_id_owner"),
        CheckConstraint(
            "career_path IN ('undecided','phd','employment','both')", name="career_path_valid"
        ),
        CheckConstraint("status IN ('active','paused','archived')", name="status_valid"),
        Index("ix_candidate_cases_owner", "owner_user_id"),
    )


class AuditEvent(Base):
    """Append-only security audit trail (not user-facing; not RLS-filtered for inserts)."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_audit_events_actor_created", "actor_user_id", "created_at"),)
    # The app role has INSERT but not SELECT on this table, so never use INSERT ... RETURNING.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
