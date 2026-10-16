"""Account-level data rights: export everything, delete everything (spec §4.1, §15)."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.domain.errors import AuthenticationFailed
from nexscout.infrastructure.db.models import (
    Affiliation,
    AuthSession,
    CandidateCase,
    CasePreferences,
    Document,
    FactEvidence,
    ProfileFact,
    ProfileSnapshot,
    SocialProfile,
    User,
)
from nexscout.infrastructure.security.passwords import verify_password
from nexscout.infrastructure.storage import ObjectStore

_EXCLUDE = {"owner_user_id", "text_content", "storage_key"}


def _row(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.key in _EXCLUDE:
            continue
        value = getattr(obj, col.key)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, uuid.UUID):
            value = str(value)
        out[col.key] = value
    return out


async def export_account(
    session: AsyncSession, actor: Actor, store: ObjectStore
) -> tuple[str, bytes]:
    """A zip containing data.json (everything we hold about you) and your original files."""
    user = await session.get(User, actor.user_id)
    if user is None:
        raise AuthenticationFailed("Account not found.")
    owned = {
        "cases": CandidateCase,
        "documents": Document,
        "profile_facts": ProfileFact,
        "fact_evidence": FactEvidence,
        "profile_snapshots": ProfileSnapshot,
        "preferences": CasePreferences,
        "social_profiles": SocialProfile,
        "affiliations": Affiliation,
    }
    payload: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "format": "nexscout-export/1",
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        },
    }
    documents: list[Document] = []
    for name, model in owned.items():
        rows = list(
            await session.scalars(
                select(model).where(model.owner_user_id == actor.user_id)  # type: ignore[attr-defined]
            )
        )
        payload[name] = [_row(r) for r in rows]
        if model is Document:
            documents = rows  # type: ignore[assignment]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("data.json", json.dumps(payload, indent=2, ensure_ascii=False))
        for doc in documents:
            try:
                blob = await asyncio.to_thread(store.get, doc.storage_key)
            except FileNotFoundError:
                continue
            zf.writestr(f"documents/{doc.id}/{doc.filename}", blob)
    record_audit(
        session,
        "account.exported",
        actor_user_id=actor.user_id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"documents": len(documents)},
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"nexscout-export-{stamp}.zip", buf.getvalue()


async def delete_account(
    session: AsyncSession, actor: Actor, store: ObjectStore, *, password: str
) -> None:
    """Permanently delete the account, all cases and data, and stored files."""
    user = await session.get(User, actor.user_id)
    if user is None or not verify_password(user.password_hash, password):
        raise AuthenticationFailed("Password is incorrect.")
    keys = list(
        await session.scalars(
            select(Document.storage_key).where(Document.owner_user_id == actor.user_id)
        )
    )
    record_audit(
        session,
        "account.deleted",
        actor_user_id=None,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"user_id": str(actor.user_id)},
    )
    await session.execute(delete(AuthSession).where(AuthSession.user_id == actor.user_id))
    await session.delete(user)  # cascades to cases and everything owned
    await session.commit()
    for key in set(keys):
        await asyncio.to_thread(store.delete, key)
