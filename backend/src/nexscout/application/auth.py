"""Authentication use cases: register, login, logout, session resolution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.config import Settings
from nexscout.domain.errors import AuthenticationFailed, Conflict, RateLimited, ValidationFailed
from nexscout.infrastructure.db.models import AuthSession, LoginAttempt, User
from nexscout.infrastructure.security.passwords import (
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)
from nexscout.infrastructure.security.tokens import new_token, token_digest, tokens_equal

MAX_DISPLAY_NAME = 120


@dataclass(frozen=True)
class IssuedSession:
    session_id: uuid.UUID
    user_id: uuid.UUID
    token: str  # raw; only returned once to be set as an httpOnly cookie
    csrf_token: str
    expires_at: datetime


@dataclass(frozen=True)
class ResolvedSession:
    actor: Actor
    csrf_hash: str


def normalize_email(email: str) -> str:
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValidationFailed("Enter a valid email address.") from exc


def _now() -> datetime:
    return datetime.now(UTC)


async def register_user(
    session: AsyncSession, *, email: str, password: str, display_name: str, ip: str | None
) -> User:
    email_n = normalize_email(email)
    validate_password_policy(password)
    name = " ".join(display_name.split())
    if not name or len(name) > MAX_DISPLAY_NAME:
        raise ValidationFailed(f"Display name must be 1-{MAX_DISPLAY_NAME} characters.")

    user = User(email=email_n, password_hash=hash_password(password), display_name=name)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Callers see a generic conflict; it doesn't say whether this is a unique-email collision
        # or something else.
        raise Conflict("An account with this email may already exist.") from exc
    record_audit(session, "user.registered", actor_user_id=user.id, ip=ip)
    return user


async def _check_rate_limit(
    session: AsyncSession, settings: Settings, email_hash: str, ip: str | None
) -> None:
    since = _now() - timedelta(minutes=1)
    limit = settings.login_rate_limit_per_minute
    by_email = await session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email_hash == email_hash,
            LoginAttempt.created_at >= since,
            LoginAttempt.succeeded.is_(False),
        )
    )
    if (by_email or 0) >= limit:
        raise RateLimited("Too many login attempts. Wait a minute and try again.")
    if ip:
        by_ip = await session.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.ip == ip,
                LoginAttempt.created_at >= since,
                LoginAttempt.succeeded.is_(False),
            )
        )
        if (by_ip or 0) >= limit * 5:
            raise RateLimited("Too many login attempts. Wait a minute and try again.")


async def login(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> IssuedSession:
    try:
        email_n = normalize_email(email)
    except ValidationFailed:
        email_n = email.strip().lower()
    email_hash = token_digest(email_n)
    await _check_rate_limit(session, settings, email_hash, ip)

    user = await session.scalar(select(User).where(User.email == email_n))
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        session.add(LoginAttempt(email_hash=email_hash, ip=ip, succeeded=False))
        record_audit(
            session, "auth.login_failed", actor_user_id=None, ip=ip, meta={"email_hash": email_hash}
        )
        raise AuthenticationFailed("Incorrect email or password.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    now = _now()
    token, csrf = new_token(), new_token()
    auth = AuthSession(
        user_id=user.id,
        token_hash=token_digest(token),
        csrf_hash=token_digest(csrf),
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=settings.session_idle_hours),
        expires_at=now + timedelta(days=settings.session_absolute_days),
        ip=ip,
        user_agent=(user_agent or "")[:512] or None,
    )
    session.add(auth)
    session.add(LoginAttempt(email_hash=email_hash, ip=ip, succeeded=True))
    await session.flush()
    record_audit(
        session,
        "auth.login",
        actor_user_id=user.id,
        ip=ip,
        target_type="session",
        target_id=auth.id,
    )
    return IssuedSession(auth.id, user.id, token, csrf, auth.expires_at)


async def resolve_session(
    session: AsyncSession,
    settings: Settings,
    token: str,
    *,
    ip: str | None,
    request_id: str | None,
) -> ResolvedSession:
    now = _now()
    auth = await session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_digest(token))
    )
    if (
        auth is None
        or auth.revoked_at is not None
        or auth.expires_at <= now
        or auth.idle_expires_at <= now
    ):
        raise AuthenticationFailed("Your session has expired. Please sign in again.")
    user_active = await session.scalar(select(User.is_active).where(User.id == auth.user_id))
    if not user_active:
        raise AuthenticationFailed("Your session has expired. Please sign in again.")
    # Sliding idle expiry; written at most once a minute to limit write load.
    if (now - auth.last_seen_at) > timedelta(minutes=1):
        auth.last_seen_at = now
        auth.idle_expires_at = min(
            now + timedelta(hours=settings.session_idle_hours), auth.expires_at
        )
    return ResolvedSession(
        actor=Actor(user_id=auth.user_id, session_id=auth.id, ip=ip, request_id=request_id),
        csrf_hash=auth.csrf_hash,
    )


def csrf_valid(resolved: ResolvedSession, presented: str | None) -> bool:
    return bool(presented) and tokens_equal(token_digest(presented or ""), resolved.csrf_hash)


async def logout(session: AsyncSession, actor: Actor) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == actor.session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    record_audit(
        session,
        "auth.logout",
        actor_user_id=actor.user_id,
        ip=actor.ip,
        request_id=actor.request_id,
        target_type="session",
        target_id=actor.session_id,
    )


async def get_user(session: AsyncSession, actor: Actor) -> User:
    user = await session.get(User, actor.user_id)
    if user is None:
        raise AuthenticationFailed("Account not found.")
    return user
