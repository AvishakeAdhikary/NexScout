"""What every workflow node receives (LangGraph `Runtime.context`).

Nodes never get raw DB access across tenants. `tenant()` yields a session bound to the run owner
(RLS applies). Approvals, side effects and step tracking are deterministic helpers that follow
ADR-0008: nodes are at-least-once, so everything here is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexscout.agent_runtime import events
from nexscout.config import Settings
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import ApprovalRequest, RunStep, ToolExecution
from nexscout.infrastructure.storage import ObjectStore


class UncertainOutcome(Exception):
    """A side effect started earlier but its result is unknown; needs reconciliation."""


class ApprovalRejected(Exception):
    pass


@dataclass
class RunContext:
    run_id: uuid.UUID
    owner_user_id: uuid.UUID
    case_id: uuid.UUID
    params: dict[str, Any]
    settings: Settings
    app_sessions: async_sessionmaker[AsyncSession]
    system_sessions: async_sessionmaker[AsyncSession]
    store: ObjectStore
    on_step_finished: Callable[[str, str], Awaitable[None]] | None = None
    extras: dict[str, Any] = field(default_factory=dict)
    _notes: dict[uuid.UUID, list[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------ sessions & events
    @asynccontextmanager
    async def tenant(self) -> AsyncIterator[AsyncSession]:
        """A committed-on-success transaction bound to the run owner (RLS enforced)."""
        async with self.app_sessions() as session, session.begin():
            await bind_tenant(session, self.owner_user_id)
            yield session

    async def emit(self, type: str, payload: dict[str, Any] | None = None) -> None:
        async with self.system_sessions() as s, s.begin():
            await events.emit(
                s,
                owner_user_id=self.owner_user_id,
                case_id=self.case_id,
                run_id=self.run_id,
                type=type,
                payload=payload,
            )

    # ------------------------------------------------------------------------ step tracking
    async def step_started(self, node: str) -> uuid.UUID:
        step_id = uuid.uuid4()
        async with self.system_sessions() as s, s.begin():
            s.add(
                RunStep(
                    id=step_id,
                    owner_user_id=self.owner_user_id,
                    run_id=self.run_id,
                    node=node,
                    status="running",
                )
            )
            await events.emit(
                s,
                owner_user_id=self.owner_user_id,
                case_id=self.case_id,
                run_id=self.run_id,
                type="step_started",
                payload={"node": node},
            )
        self._notes[step_id] = []
        return step_id

    async def note(self, step_id: uuid.UUID | None, message: str) -> None:
        """A short, user-readable progress message for the current step."""
        if step_id is not None:
            self._notes.setdefault(step_id, []).append(message[:300])
        await self.emit("step_progress", {"message": message[:300]})

    async def step_finished(
        self,
        step_id: uuid.UUID,
        node: str,
        status: str,
        *,
        error: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        notes = self._notes.pop(step_id, [])
        async with self.system_sessions() as s, s.begin():
            step = await s.get(RunStep, step_id)
            if step is not None:
                step.status = status
                step.error = error[:1000] if error else None
                step.summary = {**(summary or {}), "notes": notes}
                step.finished_at = datetime.now(UTC)
            await events.emit(
                s,
                owner_user_id=self.owner_user_id,
                case_id=self.case_id,
                run_id=self.run_id,
                type=f"step_{status}",
                payload={"node": node, "error": error, "notes": notes[-3:]},
            )
        if self.on_step_finished is not None and status == "succeeded":
            await self.on_step_finished(node, status)

    # ----------------------------------------------------------------------------- approvals
    async def require_approval(
        self,
        *,
        node: str,
        action_kind: str,
        title: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Pause the graph until the user decides. Returns True only if approved.

        The decision is read from `approval_requests` (written by the authenticated API),
        never taken from the resume payload or from model output.
        """
        key = f"{self.run_id}:{node}:{action_kind}"
        async with self.tenant() as s:
            created = await s.execute(
                insert(ApprovalRequest)
                .values(
                    id=uuid.uuid4(),
                    owner_user_id=self.owner_user_id,
                    case_id=self.case_id,
                    run_id=self.run_id,
                    node=node,
                    action_kind=action_kind,
                    title=title[:300],
                    summary=summary[:4000],
                    details=details or {},
                    status="pending",
                    idempotency_key=key,
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
            )
            row = await s.scalar(
                select(ApprovalRequest).where(ApprovalRequest.idempotency_key == key)
            )
            assert row is not None
            status, approval_id = row.status, row.id
        if status == "pending":
            if created.rowcount:  # type: ignore[attr-defined]
                await self.emit(
                    "approval_required", {"approval_id": str(approval_id), "title": title}
                )
            interrupt({"approval_id": str(approval_id), "title": title})  # stops here
            async with self.tenant() as s:
                row = await s.get(ApprovalRequest, approval_id)
                status = row.status if row else "cancelled"
        return status == "approved"

    # ------------------------------------------------------------------- side-effect ledger
    async def side_effect(
        self,
        *,
        tool: str,
        key: str,
        request: dict[str, Any],
        call: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Run an external side effect at most once per idempotency key.

        - succeeded before → return the recorded result (no repeat)
        - started before but never finished (crash) → mark `uncertain` and raise
        """
        ikey = f"{self.run_id}:{tool}:{key}"
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, default=str).encode()
        ).hexdigest()
        uncertain = False
        async with self.tenant() as s:
            row = await s.scalar(select(ToolExecution).where(ToolExecution.idempotency_key == ikey))
            if row is not None and row.status == "succeeded":
                return dict(row.response or {})
            if row is not None and row.status in ("started", "uncertain"):
                # Record the uncertainty (this transaction commits), then stop below.
                row.status = "uncertain"
                row.error = "Interrupted before the outcome was recorded."
                uncertain = True
            else:
                if row is not None:  # a recorded failure may be retried
                    await s.delete(row)
                    await s.flush()
                s.add(
                    ToolExecution(
                        owner_user_id=self.owner_user_id,
                        run_id=self.run_id,
                        tool=tool,
                        idempotency_key=ikey,
                        status="started",
                        request_digest=digest,
                    )
                )
        if uncertain:  # never repeat a side effect whose outcome is unknown
            raise UncertainOutcome(
                f"{tool}: an earlier attempt may or may not have completed. "
                "Check the result before trying again."
            )
        try:
            response = await call()
        except Exception as exc:
            async with self.tenant() as s:
                row = await s.scalar(
                    select(ToolExecution).where(ToolExecution.idempotency_key == ikey)
                )
                if row is not None:
                    row.status, row.error = "failed", f"{type(exc).__name__}: {exc}"[:1000]
                    row.finished_at = datetime.now(UTC)
            raise
        async with self.tenant() as s:
            row = await s.scalar(select(ToolExecution).where(ToolExecution.idempotency_key == ikey))
            if row is not None:
                row.status, row.response = "succeeded", response
                row.finished_at = datetime.now(UTC)
        return response
