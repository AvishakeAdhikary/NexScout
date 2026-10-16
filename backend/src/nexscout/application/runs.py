"""Run control use cases: start, inspect, pause, resume, cancel, retry, rerun/skip a step, and
decide approvals. Every transition is validated by RUN_MACHINE; workers honour durable control
requests at safe points (ADR-0008)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.agent_runtime import events, queue
from nexscout.agent_runtime.registry import get_workflow, workflows
from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.application.cases import get_case
from nexscout.domain.errors import (
    ConcurrencyConflict,
    InvalidTransition,
    NotFound,
    ValidationFailed,
)
from nexscout.domain.state_machines import RUN_MACHINE, RunStatus
from nexscout.infrastructure.db.models import (
    ApprovalRequest,
    RunStep,
    Task,
    WorkflowEvent,
    WorkflowRun,
)

MAX_PARAMS_BYTES = 10_000


@dataclass
class RunDetail:
    run: WorkflowRun
    steps: list[RunStep]
    approvals: list[ApprovalRequest]
    events: list[WorkflowEvent]


async def _get_run(
    session: AsyncSession, actor: Actor, run_id: uuid.UUID, lock: bool = False
) -> WorkflowRun:
    stmt = select(WorkflowRun).where(
        WorkflowRun.id == run_id, WorkflowRun.owner_user_id == actor.user_id
    )
    if lock:
        stmt = stmt.with_for_update()
    run = await session.scalar(stmt)
    if run is None:
        raise NotFound("Run not found.")
    return run


async def _transition(
    session: AsyncSession,
    actor: Actor,
    run: WorkflowRun,
    target: RunStatus,
    event: str,
    payload: dict[str, Any] | None = None,
    **fields: Any,
) -> None:
    RUN_MACHINE.transition(RunStatus(run.status), target)
    run.status = target.value
    for k, v in fields.items():
        setattr(run, k, v)
    if target in (RunStatus.CANCELLED, RunStatus.PAUSED):
        run.control_request = None
    if target is RunStatus.CANCELLED:
        run.finished_at = datetime.now(UTC)
    run.version += 1
    await events.emit(
        session,
        owner_user_id=actor.user_id,
        case_id=run.case_id,
        run_id=run.id,
        type=event,
        payload={"status": target.value, **(payload or {})},
    )


async def _enqueue(
    session: AsyncSession,
    actor: Actor,
    run: WorkflowRun,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    ok = await queue.enqueue(
        session,
        owner_user_id=actor.user_id,
        run_id=run.id,
        action=action,
        idempotency_key=f"{run.id}:{action}:{run.version}:{uuid.uuid4()}",
        payload=payload,
    )
    if not ok:
        raise ConcurrencyConflict("This run already has work queued. Try again in a moment.")


async def _cancel_queued(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        update(Task)
        .where(Task.run_id == run_id, Task.status == "queued")
        .values(status="cancelled", finished_at=datetime.now(UTC))
    )


def check_params(kind: str, params: dict[str, Any]) -> None:
    import json

    if len(json.dumps(params)) > MAX_PARAMS_BYTES:
        raise ValidationFailed("Run parameters are too large.")
    if kind == "system_check":
        allowed = {"wait_s", "require_approval", "marker_file"}
        if set(params) - allowed:
            raise ValidationFailed(f"Unknown parameters: {sorted(set(params) - allowed)}")


async def start_run(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, *, kind: str, params: dict[str, Any]
) -> WorkflowRun:
    await get_case(session, actor, case_id)
    spec = get_workflow(kind)
    if spec is None or not spec.user_startable:
        raise ValidationFailed("Unknown workflow.")
    check_params(kind, params)
    run = WorkflowRun(
        owner_user_id=actor.user_id,
        case_id=case_id,
        kind=kind,
        title=spec.title,
        params=params,
        status=RunStatus.PENDING.value,
    )
    session.add(run)
    await session.flush()
    await events.emit(
        session,
        owner_user_id=actor.user_id,
        case_id=case_id,
        run_id=run.id,
        type="run_created",
        payload={"kind": kind, "title": spec.title},
    )
    await _enqueue(session, actor, run, "start")
    record_audit(
        session,
        "run.started",
        actor_user_id=actor.user_id,
        target_type="run",
        target_id=run.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"kind": kind},
    )
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, limit: int = 50
) -> list[WorkflowRun]:
    await get_case(session, actor, case_id)
    return list(
        await session.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.case_id == case_id, WorkflowRun.owner_user_id == actor.user_id)
            .order_by(WorkflowRun.created_at.desc())
            .limit(min(limit, 200))
        )
    )


async def get_run(session: AsyncSession, actor: Actor, run_id: uuid.UUID) -> RunDetail:
    run = await _get_run(session, actor, run_id)
    steps = list(
        await session.scalars(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.started_at)
        )
    )
    approvals = list(
        await session.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.run_id == run_id)
            .order_by(ApprovalRequest.created_at)
        )
    )
    evts = list(
        await session.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.run_id == run_id)
            .order_by(WorkflowEvent.id.desc())
            .limit(100)
        )
    )
    return RunDetail(run, steps, approvals, list(reversed(evts)))


async def control(
    session: AsyncSession, actor: Actor, run_id: uuid.UUID, action: str, *, node: str | None = None
) -> WorkflowRun:
    run = await _get_run(session, actor, run_id, lock=True)
    status = RunStatus(run.status)
    try:
        if action == "pause":
            if status in (RunStatus.PENDING, RunStatus.WAITING_APPROVAL):
                await _cancel_queued(session, run.id)
                await _transition(session, actor, run, RunStatus.PAUSED, "run_paused")
            elif status is RunStatus.RUNNING:
                run.control_request = "pause"
                await _transition(session, actor, run, RunStatus.PAUSING, "run_pausing")
            else:
                raise InvalidTransition(f"A {status.value} run can't be paused.")
        elif action == "resume":
            if status is not RunStatus.PAUSED:
                raise InvalidTransition(
                    f"Only paused runs can be resumed (this one is {status.value})."
                )
            await _transition(session, actor, run, RunStatus.PENDING, "run_resumed")
            await _enqueue(session, actor, run, "resume")
        elif action == "cancel":
            if status in (RunStatus.PENDING, RunStatus.PAUSED, RunStatus.WAITING_APPROVAL):
                await _cancel_queued(session, run.id)
                if status is RunStatus.PENDING:
                    await _transition(session, actor, run, RunStatus.CANCELLED, "run_cancelled")
                else:
                    await _transition(session, actor, run, RunStatus.CANCELLING, "run_cancelling")
                    await _transition(session, actor, run, RunStatus.CANCELLED, "run_cancelled")
                await session.execute(
                    update(ApprovalRequest)
                    .where(ApprovalRequest.run_id == run.id, ApprovalRequest.status == "pending")
                    .values(status="cancelled", decided_at=datetime.now(UTC))
                )
            elif status in (RunStatus.RUNNING, RunStatus.PAUSING):
                run.control_request = "cancel"
                await _transition(session, actor, run, RunStatus.CANCELLING, "run_cancelling")
            else:
                raise InvalidTransition(f"A {status.value} run can't be cancelled.")
        elif action == "retry":
            if status is not RunStatus.FAILED:
                raise InvalidTransition("Only failed runs can be retried.")
            await _transition(session, actor, run, RunStatus.PENDING, "run_retry", error=None)
            await _enqueue(session, actor, run, "retry")
        elif action in ("rerun", "skip"):
            spec = get_workflow(run.kind)
            if spec is None or not node:
                raise ValidationFailed("Choose a step.")
            graph_nodes = set(spec.build().nodes)
            if node not in graph_nodes:
                raise ValidationFailed("Unknown step.")
            if action == "skip" and node not in spec.optional_nodes:
                raise ValidationFailed("This step is required and can't be skipped.")
            if status not in (RunStatus.FAILED, RunStatus.PAUSED, RunStatus.SUCCEEDED):
                raise InvalidTransition("Pause the run before changing its steps.")
            await _transition(
                session,
                actor,
                run,
                RunStatus.PENDING,
                f"run_{action}",
                payload={"node": node},
                error=None,
                finished_at=None,
            )
            await _enqueue(session, actor, run, action, {"node": node})
        else:
            raise ValidationFailed("Unknown action.")
    except InvalidTransition as exc:
        raise InvalidTransition(str(exc).replace("workflow_run: ", "")) from exc
    record_audit(
        session,
        f"run.{action}",
        actor_user_id=actor.user_id,
        target_type="run",
        target_id=run.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"node": node} if node else {},
    )
    await session.flush()
    await session.refresh(run)
    return run


# --------------------------------------------------------------------------------- approvals
async def list_approvals(
    session: AsyncSession, actor: Actor, case_id: uuid.UUID, status: str | None = "pending"
) -> list[ApprovalRequest]:
    await get_case(session, actor, case_id)
    stmt = select(ApprovalRequest).where(
        ApprovalRequest.case_id == case_id, ApprovalRequest.owner_user_id == actor.user_id
    )
    if status:
        stmt = stmt.where(ApprovalRequest.status == status)
    return list(await session.scalars(stmt.order_by(ApprovalRequest.created_at.desc())))


async def decide(
    session: AsyncSession, actor: Actor, approval_id: uuid.UUID, *, approve: bool, note: str | None
) -> ApprovalRequest:
    row = await session.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.owner_user_id == actor.user_id)
        .with_for_update()
    )
    if row is None:
        raise NotFound("Approval request not found.")
    if row.status != "pending":
        raise InvalidTransition(f"This request was already {row.status}.")
    row.status = "approved" if approve else "rejected"
    row.decision_note = (note or "").strip()[:2000] or None
    row.decided_at = datetime.now(UTC)
    run = await _get_run(session, actor, row.run_id, lock=True)
    await events.emit(
        session,
        owner_user_id=actor.user_id,
        case_id=run.case_id,
        run_id=run.id,
        type="approval_decided",
        payload={"approval_id": str(row.id), "approved": approve},
    )
    if run.status == RunStatus.WAITING_APPROVAL.value:
        await _enqueue(
            session,
            actor,
            run,
            "resume",
            {"resume": {"approval_id": str(row.id), "approved": approve}},
        )
    record_audit(
        session,
        "approval.decided",
        actor_user_id=actor.user_id,
        target_type="approval",
        target_id=row.id,
        ip=actor.ip,
        request_id=actor.request_id,
        meta={"approved": approve, "action": row.action_kind},
    )
    return row


def available_workflows() -> list[dict[str, Any]]:
    return [
        {
            "kind": w.kind,
            "title": w.title,
            "description": w.description,
            "optional_steps": sorted(w.optional_nodes),
        }
        for w in workflows().values()
        if w.user_startable
    ]
