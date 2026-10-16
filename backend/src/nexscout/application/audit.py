"""Security audit logging."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.infrastructure.db.models import AuditEvent


def record_audit(
    session: AsyncSession,
    action: str,
    *,
    actor_user_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    ip: str | None = None,
    request_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Stage an audit row in the caller's transaction (commits or rolls back with it)."""
    session.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            request_id=request_id,
            meta=meta or {},
        )
    )
