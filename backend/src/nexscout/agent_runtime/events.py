"""Workflow activity events: durable rows plus a NOTIFY wake-up (ADR-0006)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections import defaultdict
from typing import Any

import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.infrastructure.db.models import WorkflowEvent
from nexscout.observability import get_logger

CHANNEL = "nexscout_events"
log = get_logger("nexscout.events")


async def emit(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    case_id: uuid.UUID,
    run_id: uuid.UUID | None,
    type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Stage an event in the caller's transaction; NOTIFY is delivered on commit."""
    session.add(
        WorkflowEvent(
            owner_user_id=owner_user_id,
            case_id=case_id,
            run_id=run_id,
            type=type,
            payload=payload or {},
        )
    )
    await session.execute(
        text("SELECT pg_notify(:ch, :payload)"), {"ch": CHANNEL, "payload": str(case_id)}
    )


class EventHub:
    """One LISTEN connection per process that wakes the SSE streams waiting on a case."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._waiters: dict[str, set[asyncio.Event]] = defaultdict(set)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="event-hub")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    def subscribe(self, case_id: str) -> asyncio.Event:
        ev = asyncio.Event()
        self._waiters[case_id].add(ev)
        return ev

    def unsubscribe(self, case_id: str, ev: asyncio.Event) -> None:
        self._waiters[case_id].discard(ev)
        if not self._waiters[case_id]:
            self._waiters.pop(case_id, None)

    async def _run(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True, connect_timeout=5
                ) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    async for note in conn.notifies():
                        for ev in list(self._waiters.get(note.payload, ())):
                            ev.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - reconnect; SSE falls back to polling
                log.warning("event_hub_reconnect", error=type(exc).__name__)
                # Wake everyone so they poll once while we reconnect.
                for waiters in list(self._waiters.values()):
                    for ev in list(waiters):
                        ev.set()
                await asyncio.sleep(2)


def sse_format(event_id: int, event_type: str, data: dict[str, Any]) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {json.dumps(data, default=str)}\n\n"
