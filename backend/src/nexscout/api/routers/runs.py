"""Workflow runs, controls, approvals, and the live activity stream (SSE)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy import select

from nexscout.agent_runtime.events import EventHub, sse_format
from nexscout.api.deps import CurrentActor, DbSession
from nexscout.api.schemas import ApiModel
from nexscout.application import runs
from nexscout.application.cases import get_case
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.db.models import WorkflowEvent

router = APIRouter(tags=["runs"])
HEARTBEAT_S = 15.0


class RunStart(ApiModel):
    kind: str = Field(max_length=60)
    params: dict[str, Any] = Field(default_factory=dict)


class RunOut(ApiModel):
    id: uuid.UUID
    case_id: uuid.UUID
    kind: str
    title: str
    status: str
    control_request: str | None
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    current_node: str | None
    steps_completed: int
    step_budget: int
    tokens_used: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    version: int


class StepOut(ApiModel):
    id: uuid.UUID
    node: str
    status: str
    summary: dict[str, Any]
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ApprovalOut(ApiModel):
    id: uuid.UUID
    run_id: uuid.UUID
    node: str
    action_kind: str
    title: str
    summary: str
    details: dict[str, Any]
    status: str
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime


class EventOut(ApiModel):
    id: int
    run_id: uuid.UUID | None
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunDetailOut(ApiModel):
    run: RunOut
    steps: list[StepOut]
    approvals: list[ApprovalOut]
    events: list[EventOut]


class ControlIn(ApiModel):
    action: str = Field(pattern="^(pause|resume|cancel|retry|rerun|skip)$")
    node: str | None = Field(default=None, max_length=100)


class DecisionIn(ApiModel):
    approve: bool
    note: str | None = Field(default=None, max_length=2000)


class WorkflowOut(ApiModel):
    kind: str
    title: str
    description: str
    optional_steps: list[str]


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(actor: CurrentActor) -> list[WorkflowOut]:
    return [WorkflowOut(**w) for w in runs.available_workflows()]


@router.post("/cases/{case_id}/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def start_run(
    case_id: uuid.UUID, body: RunStart, actor: CurrentActor, db: DbSession
) -> RunOut:
    return RunOut.model_validate(
        await runs.start_run(db, actor, case_id, kind=body.kind, params=body.params)
    )


@router.get("/cases/{case_id}/runs", response_model=list[RunOut])
async def list_runs(case_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> list[RunOut]:
    return [RunOut.model_validate(r) for r in await runs.list_runs(db, actor, case_id)]


@router.get("/runs/{run_id}", response_model=RunDetailOut)
async def get_run(run_id: uuid.UUID, actor: CurrentActor, db: DbSession) -> RunDetailOut:
    d = await runs.get_run(db, actor, run_id)
    return RunDetailOut(
        run=RunOut.model_validate(d.run),
        steps=[StepOut.model_validate(s) for s in d.steps],
        approvals=[ApprovalOut.model_validate(a) for a in d.approvals],
        events=[EventOut.model_validate(e) for e in d.events],
    )


@router.post("/runs/{run_id}/control", response_model=RunOut)
async def control(run_id: uuid.UUID, body: ControlIn, actor: CurrentActor, db: DbSession) -> RunOut:
    return RunOut.model_validate(await runs.control(db, actor, run_id, body.action, node=body.node))


@router.get("/cases/{case_id}/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    case_id: uuid.UUID, actor: CurrentActor, db: DbSession, status: str | None = "pending"
) -> list[ApprovalOut]:
    return [
        ApprovalOut.model_validate(a)
        for a in await runs.list_approvals(db, actor, case_id, status or None)
    ]


class ApprovalDetailOut(ApprovalOut):
    case_id: uuid.UUID


@router.get("/approvals/{approval_id}", response_model=ApprovalDetailOut)
async def get_approval(
    approval_id: uuid.UUID, actor: CurrentActor, db: DbSession
) -> ApprovalDetailOut:
    """One approval (the page a notification links to)."""
    return ApprovalDetailOut.model_validate(await runs.get_approval(db, actor, approval_id))


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide(
    approval_id: uuid.UUID, body: DecisionIn, actor: CurrentActor, db: DbSession
) -> ApprovalOut:
    return ApprovalOut.model_validate(
        await runs.decide(db, actor, approval_id, approve=body.approve, note=body.note)
    )


@router.get("/cases/{case_id}/events")
async def event_stream(
    case_id: uuid.UUID,
    request: Request,
    actor: CurrentActor,
    db: DbSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = None,
    once: bool = False,
) -> StreamingResponse:
    """Server-Sent Events for a case. Replays from `Last-Event-ID` (or `after`), then streams.

    `once=true` returns the backlog and closes (used by tests and simple polling clients).
    """
    await get_case(db, actor, case_id)  # authorize now; the stream uses fresh sessions
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else (after or 0)
    maker = request.app.state.sessionmaker
    hub: EventHub | None = getattr(request.app.state, "event_hub", None)
    user_id = actor.user_id

    async def backlog(since: int) -> list[WorkflowEvent]:
        async with maker() as s, s.begin():
            await bind_tenant(s, user_id)
            return list(
                await s.scalars(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.case_id == case_id, WorkflowEvent.id > since)
                    .order_by(WorkflowEvent.id)
                    .limit(500)
                )
            )

    async def gen() -> AsyncIterator[str]:
        nonlocal cursor
        waiter = hub.subscribe(str(case_id)) if hub else None
        try:
            yield ": connected\n\n"
            while True:
                for ev in await backlog(cursor):
                    cursor = ev.id
                    yield sse_format(
                        ev.id,
                        ev.type,
                        {"run_id": ev.run_id, **ev.payload, "created_at": ev.created_at},
                    )
                if once or await request.is_disconnected():
                    return
                if waiter is None:
                    await asyncio.sleep(2)
                    continue
                waiter.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(waiter.wait(), timeout=HEARTBEAT_S)
                if not waiter.is_set():
                    yield ": keep-alive\n\n"
        finally:
            if hub and waiter:
                hub.unsubscribe(str(case_id), waiter)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        # no-transform: stops proxies (including the Next.js dev server) from compressing,
        # and so buffering, the stream.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
