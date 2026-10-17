"""Personal access tokens: created by the user, shown once, stored as a digest, revocable.

They grant read-only access for local integrations (the MCP server). They can't be used to log
in to the web app and never authorize consequential actions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.domain.errors import AuthenticationFailed, NotFound, ValidationFailed
from nexscout.infrastructure.db.models import PersonalAccessToken, User
from nexscout.infrastructure.security.tokens import new_token, token_digest

PREFIX = "nxs_"
SCOPES = frozenset({"read"})
MAX_TOKENS = 20


async def create_token(
    s: AsyncSession, actor: Actor, *, name: str, expires_in_days: int | None
) -> tuple[PersonalAccessToken, str]:
    name = name.strip()
    if not name:
        raise ValidationFailed("Give the token a name.")
    count = len(
        list(
            await s.scalars(
                select(PersonalAccessToken.id).where(
                    PersonalAccessToken.user_id == actor.user_id,
                    PersonalAccessToken.revoked_at.is_(None),
                )
            )
        )
    )
    if count >= MAX_TOKENS:
        raise ValidationFailed("Revoke an old token first.")
    plain = PREFIX + new_token()
    row = PersonalAccessToken(
        user_id=actor.user_id,
        name=name[:100],
        token_hash=token_digest(plain),
        prefix=plain[:10],
        scopes=sorted(SCOPES),
        expires_at=(datetime.now(UTC) + timedelta(days=expires_in_days))
        if expires_in_days
        else None,
    )
    s.add(row)
    await s.flush()
    record_audit(
        s,
        "token.created",
        actor_user_id=actor.user_id,
        target_type="token",
        target_id=row.id,
        meta={"name": row.name},
    )
    return row, plain


async def list_tokens(s: AsyncSession, actor: Actor) -> list[PersonalAccessToken]:
    return list(
        await s.scalars(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == actor.user_id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
    )


async def revoke_token(s: AsyncSession, actor: Actor, token_id: uuid.UUID) -> None:
    row = await s.scalar(
        select(PersonalAccessToken).where(
            PersonalAccessToken.id == token_id, PersonalAccessToken.user_id == actor.user_id
        )
    )
    if row is None:
        raise NotFound("Token not found.")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        record_audit(
            s, "token.revoked", actor_user_id=actor.user_id, target_type="token", target_id=row.id
        )


async def authenticate_token(s: AsyncSession, plain: str) -> uuid.UUID:
    """The user a token belongs to. Same error for every failure (no oracle)."""
    fail = AuthenticationFailed("Invalid or expired token.")
    if not plain.startswith(PREFIX) or len(plain) > 200:
        raise fail
    row = await s.scalar(
        select(PersonalAccessToken).where(PersonalAccessToken.token_hash == token_digest(plain))
    )
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or (row.expires_at and row.expires_at <= now):
        raise fail
    active = await s.scalar(select(User.is_active).where(User.id == row.user_id))
    if not active:
        raise fail
    row.last_used_at = now
    return row.user_id
