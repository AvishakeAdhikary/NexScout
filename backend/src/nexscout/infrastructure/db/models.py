"""ORM models. Owned tables carry owner_user_id and are protected by Postgres RLS (ADR-0003)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
OWNED_TABLES: tuple[str, ...] = (
    "candidate_cases",
    "documents",
    "profile_facts",
    "fact_evidence",
    "profile_snapshots",
    "case_preferences",
    "social_profiles",
    "affiliations",
)


def case_fk() -> ForeignKeyConstraint:
    """Composite FK: a child row can only reference a case owned by the same user."""
    return ForeignKeyConstraint(
        ["case_id", "owner_user_id"],
        ["candidate_cases.id", "candidate_cases.owner_user_id"],
        ondelete="CASCADE",
    )


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


# --------------------------------------------------------------------------- M2: profile
class Document(IdMixin, TimestampMixin, Base):
    """An uploaded (or later, generated) file. The original bytes live in the ObjectStore."""

    __tablename__ = "documents"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    file_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    parse_error: Mapped[str | None] = mapped_column(String(500))
    page_count: Mapped[int | None] = mapped_column(Integer)
    text_content: Mapped[str | None] = mapped_column(Text)
    page_starts: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    extraction_method: Mapped[str | None] = mapped_column(String(40))
    facts_extracted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        case_fk(),
        ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        UniqueConstraint("id", "owner_user_id", name="uq_documents_id_owner"),
        CheckConstraint("origin IN ('uploaded','generated')", name="origin_valid"),
        CheckConstraint("parse_status IN ('pending','parsed','failed')", name="parse_status_valid"),
        CheckConstraint("file_kind IN ('pdf','docx','markdown','text')", name="file_kind_valid"),
        Index("ix_documents_case", "case_id", "created_at"),
    )


class ProfileFact(IdMixin, TimestampMixin, Base):
    """One structured claim about the candidate. `data` is validated per section (domain)."""

    __tablename__ = "profile_facts"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    section: Mapped[str] = mapped_column(String(30), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False)
    is_private: Mapped[bool] = mapped_column(nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        UniqueConstraint("id", "owner_user_id", name="uq_profile_facts_id_owner"),
        CheckConstraint(
            "status IN ('user_entered','extracted','inferred','verified','external')",
            name="status_valid",
        ),
        CheckConstraint(
            "review_state IN ('pending','accepted','rejected')", name="review_state_valid"
        ),
        Index("ix_profile_facts_case_section", "case_id", "section"),
        Index("ix_profile_facts_case_review", "case_id", "review_state"),
    )


class FactEvidence(IdMixin, Base):
    """Where a fact came from: a document span, a URL, or the user's own entry."""

    __tablename__ = "fact_evidence"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    fact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    excerpt: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["fact_id", "owner_user_id"],
            ["profile_facts.id", "profile_facts.owner_user_id"],
            ondelete="CASCADE",
        ),
        # Deleting a document keeps the evidence row (and its excerpt) but unlinks the file.
        ForeignKeyConstraint(
            ["document_id", "owner_user_id"],
            ["documents.id", "documents.owner_user_id"],
            ondelete="SET NULL (document_id)",
        ),
        CheckConstraint("kind IN ('document','url','user_entry','merge')", name="kind_valid"),
        Index("ix_fact_evidence_fact", "fact_id"),
        Index("ix_fact_evidence_document", "document_id"),
    )


class ProfileSnapshot(IdMixin, Base):
    """Frozen copy of the accepted profile, for history and comparison."""

    __tablename__ = "profile_snapshots"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    facts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "number", name="uq_profile_snapshots_case_number"),
    )


class CasePreferences(Base):
    """Search preferences for one case (validated by domain.preferences.Preferences)."""

    __tablename__ = "case_preferences"

    case_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (case_fk(),)


class SocialProfile(IdMixin, Base):
    __tablename__ = "social_profiles"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        case_fk(),
        UniqueConstraint("case_id", "url", name="uq_social_profiles_case_url"),
    )


class Affiliation(IdMixin, TimestampMixin, Base):
    """A relationship to an organization (optionally via a named person) and how it may be used.

    A relationship is not an endorsement. Outreach may use it only when `may_use_for_referral`.
    """

    __tablename__ = "affiliations"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    case_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    person_name: Mapped[str | None] = mapped_column(String(200))  # NULL = the candidate
    organization: Mapped[str] = mapped_column(String(300), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str | None] = mapped_column(String(200))
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="current")
    evidence: Mapped[str | None] = mapped_column(String(2000))
    notes: Mapped[str | None] = mapped_column(String(2000))
    may_use_in_applications: Mapped[bool] = mapped_column(nullable=False, default=False)
    may_use_for_referral: Mapped[bool] = mapped_column(nullable=False, default=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        case_fk(),
        CheckConstraint("status IN ('current','former','unknown')", name="status_valid"),
        Index("ix_affiliations_case", "case_id"),
    )
