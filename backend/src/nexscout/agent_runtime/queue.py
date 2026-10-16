"""Postgres-backed durable task queue (ADR-0002).

Claiming, lease extension and reaping are single short SQL statements. No lock is held while a
task executes. A partial unique index guarantees at most one active task per run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.infrastructure.db.models import Task


@dataclass(frozen=True)
class ClaimedTask:
    id: uuid.UUID
    run_id: uuid.UUID
    owner_user_id: uuid.UUID
    action: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int


async def enqueue(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    run_id: uuid.UUID,
    action: str,
    idempotency_key: str,
    payload: dict[str, Any] | None = None,
    max_attempts: int = 3,
    priority: int = 100,
) -> bool:
    """Queue work for a run. Returns False if the run already has an active task or the key
    was already used (both make enqueueing idempotent)."""
    stmt = (
        insert(Task)
        .values(
            id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            run_id=run_id,
            action=action,
            payload=payload or {},
            max_attempts=max_attempts,
            priority=priority,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing()
    )
    result = await session.execute(stmt)
    await session.execute(text("SELECT pg_notify('nexscout_tasks', :r)"), {"r": str(run_id)})
    return bool(result.rowcount)  # type: ignore[attr-defined]


_CLAIM = text(
    """
    WITH busy AS (
        SELECT owner_user_id FROM tasks WHERE status = 'running'
        GROUP BY owner_user_id HAVING count(*) >= :per_user
    ), picked AS (
        SELECT t.id FROM tasks t
        WHERE t.status = 'queued' AND t.available_at <= now()
          AND t.owner_user_id NOT IN (SELECT owner_user_id FROM busy)
        ORDER BY t.priority, t.created_at
        LIMIT :n
        FOR UPDATE SKIP LOCKED
    )
    UPDATE tasks t
       SET status = 'running', lease_owner = :worker,
           lease_expires_at = now() + make_interval(secs => :lease),
           attempt = t.attempt + 1, updated_at = now()
      FROM picked
     WHERE t.id = picked.id
    RETURNING t.id, t.run_id, t.owner_user_id, t.action, t.payload, t.attempt, t.max_attempts
    """
)


async def claim(
    session: AsyncSession, *, worker_id: str, limit: int, lease_s: int, per_user: int
) -> list[ClaimedTask]:
    if limit <= 0:
        return []
    rows = (
        await session.execute(
            _CLAIM, {"n": limit, "worker": worker_id, "lease": lease_s, "per_user": per_user}
        )
    ).all()
    return [
        ClaimedTask(
            r.id, r.run_id, r.owner_user_id, r.action, r.payload or {}, r.attempt, r.max_attempts
        )
        for r in rows
    ]


async def extend_leases(
    session: AsyncSession, *, worker_id: str, task_ids: list[uuid.UUID], lease_s: int
) -> set[uuid.UUID]:
    """Returns the ids this worker still owns (a missing id means the lease was lost)."""
    if not task_ids:
        return set()
    rows = await session.execute(
        text(
            "UPDATE tasks SET lease_expires_at = now() + make_interval(secs => :lease), "
            "updated_at = now() WHERE id = ANY(:ids) AND lease_owner = :worker "
            "AND status = 'running' RETURNING id"
        ),
        {"lease": lease_s, "ids": task_ids, "worker": worker_id},
    )
    return {r.id for r in rows}


async def finish(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    worker_id: str,
    status: str,
    error: str | None = None,
) -> bool:
    """Mark a task done. Returns False if this worker no longer owns it."""
    result = await session.execute(
        text(
            "UPDATE tasks SET status = :status, finished_at = now(), lease_owner = NULL, "
            "lease_expires_at = NULL, last_error = :error, updated_at = now() "
            "WHERE id = :id AND lease_owner = :worker AND status = 'running'"
        ),
        {
            "status": status,
            "error": (error or None) and error[:1000],
            "id": task_id,
            "worker": worker_id,
        },
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def requeue(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    worker_id: str,
    delay_s: float,
    error: str | None,
    refund_attempt: bool = False,
) -> bool:
    """Put a claimed task back (retry with backoff, or after a graceful shutdown)."""
    result = await session.execute(
        text(
            "UPDATE tasks SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL, "
            "available_at = now() + make_interval(secs => :delay), last_error = :error, "
            "attempt = attempt - CASE WHEN :refund THEN 1 ELSE 0 END, updated_at = now() "
            "WHERE id = :id AND lease_owner = :worker AND status = 'running'"
        ),
        {
            "delay": delay_s,
            "error": error and error[:1000],
            "refund": refund_attempt,
            "id": task_id,
            "worker": worker_id,
        },
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ReapedTask:
    id: uuid.UUID
    run_id: uuid.UUID
    status: str  # "queued" (will be retried) or "failed" (attempts exhausted)


_REAP = text(
    """
    UPDATE tasks
       SET status = CASE WHEN attempt < max_attempts THEN 'queued' ELSE 'failed' END,
           available_at = now() + make_interval(
               secs => CASE WHEN attempt <= 1 THEN 0
                            ELSE least(300, 5 * power(2, attempt - 2)) + random() * 3 END),
           finished_at = CASE WHEN attempt < max_attempts THEN NULL ELSE now() END,
           lease_owner = NULL, lease_expires_at = NULL,
           last_error = 'The worker processing this step stopped responding.',
           updated_at = now()
     WHERE status = 'running' AND lease_expires_at < now()
    RETURNING id, run_id, status
    """
)


async def reap_expired(session: AsyncSession) -> list[ReapedTask]:
    rows = (await session.execute(_REAP)).all()
    return [ReapedTask(r.id, r.run_id, r.status) for r in rows]


def backoff_s(attempt: int) -> float:
    """Exponential backoff with a cap (jitter is added by callers via random)."""
    return float(min(300, 5 * 2 ** max(attempt - 1, 0)))
