"""The durable worker process (`nexscout worker`).

Loops: claim (leased tasks), heartbeat (extend leases, observe pause/cancel), reaper (recover
tasks from dead workers), housekeeping (purge checkpoints of deleted runs). Each claimed task
advances one run's LangGraph graph from its last Postgres checkpoint (ADR-0002, ADR-0008).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphDrained
from langgraph.runtime import RunControl
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nexscout.agent_runtime import events, queue
from nexscout.agent_runtime.channel_loops import ChannelLoops
from nexscout.agent_runtime.context import RunContext, TokenBudgetExceeded, UncertainOutcome
from nexscout.agent_runtime.errors import user_message
from nexscout.agent_runtime.registry import WorkflowSpec, get_workflow
from nexscout.config import Settings
from nexscout.domain.state_machines import RUN_MACHINE, RunStatus
from nexscout.infrastructure.db.engine import build_engine, build_sessionmaker
from nexscout.infrastructure.db.models import WorkerHeartbeat, WorkflowRun
from nexscout.infrastructure.llm.base import ProviderUnavailable
from nexscout.infrastructure.storage import LocalObjectStore
from nexscout.observability import get_logger

log = get_logger("nexscout.worker")
TASKS_CHANNEL = "nexscout_tasks"
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,
    ProviderUnavailable,
    psycopg.OperationalError,
    ConnectionError,
    TimeoutError,
)


def libpq_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


class StepBudgetExceeded(Exception):
    user_facing = True


@dataclass
class InFlight:
    task: queue.ClaimedTask
    control: RunControl = field(default_factory=RunControl)
    cancel_reason: str | None = None
    job: asyncio.Task[None] | None = None


class Worker:
    def __init__(self, settings: Settings, worker_id: str | None = None) -> None:
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._inflight: dict[uuid.UUID, InFlight] = {}
        self._graphs: dict[str, Any] = {}
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._started_at = datetime.now(UTC)
        self.app_engine: AsyncEngine | None = None
        self.system_engine: AsyncEngine | None = None
        self.app_sessions: async_sessionmaker[AsyncSession]
        self.system_sessions: async_sessionmaker[AsyncSession]
        self._pool: AsyncConnectionPool[Any] | None = None
        self.saver: AsyncPostgresSaver | None = None

    # ------------------------------------------------------------------------- lifecycle
    async def open(self) -> None:
        s = self.settings
        self.app_engine = build_engine(s)
        self.system_engine = build_engine(s, s.system_database_url.get_secret_value())
        self.app_sessions = build_sessionmaker(self.app_engine)
        self.system_sessions = build_sessionmaker(self.system_engine)
        self._pool = AsyncConnectionPool(
            libpq_url(s.system_database_url.get_secret_value()),
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            min_size=1,
            max_size=max(2, s.worker_concurrency),
            open=False,
        )
        await self._pool.open()
        async with self._pool.connection() as conn:
            row = await (await conn.execute("SELECT to_regclass('checkpoints') AS t")).fetchone()
        if not row or row["t"] is None:
            await self._pool.close()
            raise RuntimeError(
                "The database is missing the workflow checkpoint tables. "
                "Run `uv run nexscout migrate` first."
            )
        self.saver = AsyncPostgresSaver(self._pool)
        self.store = LocalObjectStore(s.storage_dir)
        await self._heartbeat_row("running")
        log.info("worker_started", worker=self.worker_id, concurrency=s.worker_concurrency)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._heartbeat_row("stopped")
        if self._pool is not None:
            await self._pool.close()
        for engine in (self.app_engine, self.system_engine):
            if engine is not None:
                await engine.dispose()
        log.info("worker_stopped", worker=self.worker_id)

    def request_stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def run_forever(self) -> None:
        await self.open()
        loops = [
            asyncio.create_task(c)
            for c in (
                self._heartbeat_loop(),
                self._reaper_loop(),
                self._listen_loop(),
                self._housekeeping_loop(),
                self._maintenance_loop(),
                *(self.channel_loops().loops() if self.settings.channels_enabled else []),
            )
        ]
        try:
            while not self._stop.is_set():
                await self._claim_and_start()
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.settings.worker_poll_s)
            await self._drain_inflight()
        finally:
            for t in loops:
                t.cancel()
            await asyncio.gather(*loops, return_exceptions=True)
            await self.close()

    async def run_until_idle(self, timeout_s: float = 60.0) -> None:
        """Test helper: process tasks until nothing is queued (now) and nothing is running."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await self._reap_once()
            started = await self._claim_and_start()
            if self._inflight:
                await asyncio.gather(
                    *(f.job for f in self._inflight.values() if f.job), return_exceptions=True
                )
                continue
            if not started:
                return
        raise TimeoutError("worker did not become idle in time")

    async def _drain_inflight(self) -> None:
        """Graceful shutdown: stop at the next step boundary, then requeue."""
        if not self._inflight:
            return
        log.info("worker_draining", tasks=len(self._inflight))
        for f in self._inflight.values():
            f.control.request_drain("shutdown")
        jobs = [f.job for f in self._inflight.values() if f.job]
        _done, pending = await asyncio.wait(jobs, timeout=self.settings.worker_shutdown_grace_s)
        for f in list(self._inflight.values()):
            if f.job in pending:
                f.cancel_reason = "shutdown"
                f.job.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # ------------------------------------------------------------------------------ loops
    async def _claim_and_start(self) -> int:
        free = self.settings.worker_concurrency - len(self._inflight)
        if free <= 0 or self._stop.is_set():
            return 0
        async with self.system_sessions() as s, s.begin():
            claimed = await queue.claim(
                s,
                worker_id=self.worker_id,
                limit=free,
                lease_s=self.settings.worker_lease_s,
                per_user=self.settings.worker_per_user_limit,
            )
        for task in claimed:
            flight = InFlight(task)
            self._inflight[task.id] = flight
            flight.job = asyncio.create_task(self._execute(flight), name=f"task-{task.id}")
        return len(claimed)

    async def _heartbeat_loop(self) -> None:
        interval = max(1.0, self.settings.worker_lease_s / 3)
        while True:
            await asyncio.sleep(interval)
            with contextlib.suppress(Exception):
                await self._heartbeat_once()

    async def _heartbeat_once(self) -> None:
        ids = list(self._inflight)
        async with self.system_sessions() as s, s.begin():
            owned = await queue.extend_leases(
                s, worker_id=self.worker_id, task_ids=ids, lease_s=self.settings.worker_lease_s
            )
            run_ids = {f.task.run_id: f for f in self._inflight.values()}
            controls = (
                await s.execute(
                    select(WorkflowRun.id, WorkflowRun.control_request).where(
                        WorkflowRun.id.in_(list(run_ids))
                    )
                )
            ).all()
        for tid in set(ids) - owned:  # lease lost: another worker may take over
            f = self._inflight.get(tid)
            if f and f.job:
                f.cancel_reason = "lease_lost"
                f.job.cancel()
        for run_id, control in controls:
            f = run_ids[run_id]
            if control == "pause":
                f.control.request_drain("pause")
            elif control == "cancel" and f.cancel_reason is None and f.job:
                f.cancel_reason = "cancel"
                f.job.cancel()
        await self._heartbeat_row("running")

    async def _heartbeat_row(self, status: str) -> None:
        now = datetime.now(UTC)
        async with self.system_sessions() as s, s.begin():
            await s.execute(
                insert(WorkerHeartbeat)
                .values(
                    worker_id=self.worker_id,
                    hostname=socket.gethostname()[:200],
                    pid=os.getpid(),
                    status=status,
                    in_flight=len(self._inflight),
                    started_at=self._started_at,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["worker_id"],
                    set_={"status": status, "in_flight": len(self._inflight), "last_seen_at": now},
                )
            )

    async def _reaper_loop(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, self.settings.worker_lease_s / 2))
            with contextlib.suppress(Exception):
                await self._reap_once()

    async def _reap_once(self) -> None:
        async with self.system_sessions() as s, s.begin():
            reaped = await queue.reap_expired(s)
        for r in reaped:
            if r.status == "queued":
                await self._set_run(
                    r.run_id,
                    RunStatus.PENDING,
                    event="run_recovering",
                    payload={
                        "message": "A worker stopped responding. Resuming from the last saved step."
                    },
                )
            else:
                await self._set_run(
                    r.run_id,
                    RunStatus.FAILED,
                    error="The worker stopped responding too many times.",
                    event="run_failed",
                )
        if reaped:
            log.warning("tasks_reaped", count=len(reaped))

    async def _listen_loop(self) -> None:
        dsn = libpq_url(self.settings.system_database_url.get_secret_value())
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
                    await conn.execute(f"LISTEN {TASKS_CHANNEL}")
                    async for _ in conn.notifies():
                        self._wake.set()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - polling covers missed notifications
                await asyncio.sleep(2)

    async def _housekeeping_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            with contextlib.suppress(Exception):
                await self.purge_orphan_checkpoints()

    async def _maintenance_loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.maintenance_once()
            with contextlib.suppress(Exception):
                await self.autopilot_once()
            await asyncio.sleep(self.settings.maintenance_interval_s)

    async def autopilot_once(self) -> dict[str, int]:
        """Start due autopilot cycles, advance autopilot items, send the daily digest (M12)."""
        from nexscout.application import autopilot

        t = await autopilot.tick(self.system_sessions, self.app_sessions, self.settings)
        sent = await autopilot.digest(self.app_sessions, self.system_sessions)
        return {"started_cycles": t.started_cycles, "advanced": t.advanced, "digests": sent}

    def channel_loops(self) -> ChannelLoops:
        """Notification delivery and chat inbound (M11). Off with NEXSCOUT_CHANNELS_ENABLED=0."""
        return ChannelLoops(self.settings, self.system_sessions, self.app_sessions, self._stop)

    async def maintenance_once(self) -> dict[str, int]:
        """Deadline reminders and in-app notifications (idempotent, see notifications.py)."""
        from nexscout.application.notifications import run_maintenance

        async with self.system_sessions() as s, s.begin():
            return await run_maintenance(s)

    async def purge_orphan_checkpoints(self) -> int:
        """Delete LangGraph state for runs that no longer exist (deleted case or account)."""
        async with self.system_sessions() as s, s.begin():
            total = 0
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                res = await s.execute(
                    text(
                        f"DELETE FROM {table} t WHERE NOT EXISTS "  # noqa: S608 - fixed table names
                        "(SELECT 1 FROM workflow_runs r WHERE r.id::text = t.thread_id)"
                    )
                )
                total += res.rowcount or 0  # type: ignore[attr-defined]
        return total

    # -------------------------------------------------------------------------- execution
    def _graph(self, spec: WorkflowSpec) -> Any:
        if spec.kind not in self._graphs:
            self._graphs[spec.kind] = spec.build().compile(checkpointer=self.saver)
        return self._graphs[spec.kind]

    async def _set_run(
        self,
        run_id: uuid.UUID,
        target: RunStatus,
        *,
        event: str | None = None,
        payload: dict[str, Any] | None = None,
        **fields: Any,
    ) -> bool:
        async with self.system_sessions() as s, s.begin():
            run = await s.get(WorkflowRun, run_id, with_for_update=True)
            if run is None:
                return False
            current = RunStatus(run.status)
            if current != target and not RUN_MACHINE.can(current, target):
                log.warning(
                    "run_transition_skipped", run=str(run_id), current=current, target=target
                )
                return False
            run.status = target.value
            for k, v in fields.items():
                setattr(run, k, v)
            if target in (RunStatus.PAUSED, RunStatus.CANCELLED):
                run.control_request = None
            if target in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
                run.finished_at = datetime.now(UTC)
            run.version += 1
            if event:
                await events.emit(
                    s,
                    owner_user_id=run.owner_user_id,
                    case_id=run.case_id,
                    run_id=run.id,
                    type=event,
                    payload={"status": target.value, **(payload or {})},
                )
        return True

    async def _finish(self, task: queue.ClaimedTask, status: str, error: str | None = None) -> None:
        async with self.system_sessions() as s, s.begin():
            await queue.finish(
                s, task_id=task.id, worker_id=self.worker_id, status=status, error=error
            )

    async def _requeue(
        self, task: queue.ClaimedTask, delay_s: float, error: str | None, refund: bool
    ) -> None:
        async with self.system_sessions() as s, s.begin():
            await queue.requeue(
                s,
                task_id=task.id,
                worker_id=self.worker_id,
                delay_s=delay_s,
                error=error,
                refund_attempt=refund,
            )

    async def _execute(self, flight: InFlight) -> None:
        task = flight.task
        try:
            await self._advance(flight)
        except Exception:
            log.exception("task_crashed", task=str(task.id))
            with contextlib.suppress(Exception):
                await self._finish(task, "failed", "Internal error in the worker.")
                await self._set_run(
                    task.run_id,
                    RunStatus.FAILED,
                    event="run_failed",
                    error="Internal error in the worker.",
                )
        finally:
            self._inflight.pop(task.id, None)
            self._wake.set()

    async def _advance(self, flight: InFlight) -> None:
        task = flight.task
        async with self.system_sessions() as s:
            run = await s.get(WorkflowRun, task.run_id)
        if run is None:
            await self._finish(task, "cancelled", "Run no longer exists.")
            return
        status = RunStatus(run.status)
        if run.control_request == "cancel" or status is RunStatus.CANCELLING:
            await self._set_run(run.id, RunStatus.CANCELLED, event="run_cancelled")
            await self._finish(task, "cancelled")
            return
        if run.control_request == "pause" or status is RunStatus.PAUSING:
            await self._set_run(run.id, RunStatus.PAUSED, event="run_paused")
            await self._finish(task, "succeeded")
            return
        spec = get_workflow(run.kind)
        if spec is None:
            await self._set_run(
                run.id, RunStatus.FAILED, event="run_failed", error=f"Unknown workflow: {run.kind}"
            )
            await self._finish(task, "failed", "unknown workflow")
            return
        if not await self._set_run(
            run.id,
            RunStatus.RUNNING,
            event="run_running",
            payload={"action": task.action, "attempt": task.attempt},
            started_at=run.started_at or datetime.now(UTC),
            error=None,
        ):
            await self._finish(task, "cancelled", f"Run is {run.status}.")
            return

        graph = self._graph(spec)
        config: dict[str, Any] = {
            "configurable": {"thread_id": str(run.id)},
            "recursion_limit": max(25, run.step_budget),
        }
        ctx = RunContext(
            run_id=run.id,
            owner_user_id=run.owner_user_id,
            case_id=run.case_id,
            params=dict(run.params),
            settings=self.settings,
            app_sessions=self.app_sessions,
            system_sessions=self.system_sessions,
            store=self.store,
            on_step_finished=self._step_counter(run.id, flight),
        )
        graph_input: Any = None
        if task.action == "start":
            # A recovered "start" task must resume, not restart: new input would begin a
            # fresh pass over the graph and repeat completed steps.
            existing = await graph.aget_state(config)
            if existing.created_at is None:
                graph_input = spec.initial_state(dict(run.params))
        elif task.action == "resume" and "resume" in task.payload:
            graph_input = Command(resume=task.payload["resume"])
        elif task.action == "rerun":
            node = str(task.payload.get("node"))
            async for snap in graph.aget_state_history(config):
                if snap.next == (node,):
                    config = snap.config
                    break
            else:
                await self._set_run(
                    run.id,
                    RunStatus.FAILED,
                    event="run_failed",
                    error=f"No saved point before step “{node}” to rerun from.",
                )
                await self._finish(task, "failed", "no checkpoint for rerun")
                return
        elif task.action == "skip":
            node = str(task.payload.get("node"))
            current = await graph.aget_state(config)
            if current.next != (node,):
                await self._set_run(
                    run.id,
                    RunStatus.FAILED,
                    event="run_failed",
                    error=f"“{node}” isn't the next step, so it can't be skipped.",
                )
                await self._finish(task, "failed", "skip target is not the next step")
                return
            await graph.aupdate_state(config, {}, as_node=node)
            await ctx.emit("step_skipped", {"node": node})

        try:
            async for _ in graph.astream(
                graph_input,
                config,
                context=ctx,
                stream_mode="updates",
                durability="sync",
                control=flight.control,
            ):
                pass
            state = await graph.aget_state({"configurable": {"thread_id": str(run.id)}})
            if state.interrupts:
                await self._set_run(
                    run.id,
                    RunStatus.WAITING_APPROVAL,
                    event="run_waiting",
                    current_node=state.next[0] if state.next else None,
                )
            elif state.next:
                await self._set_run(run.id, RunStatus.PENDING, event="run_requeued")
                await self._requeue(task, 0, "Graph stopped before finishing.", refund=True)
                return
            else:
                result = state.values.get("result") if isinstance(state.values, dict) else None
                await self._set_run(
                    run.id,
                    RunStatus.SUCCEEDED,
                    event="run_succeeded",
                    result=result,
                    current_node=None,
                )
            await self._finish(task, "succeeded")
        except GraphDrained as drained:
            drain_reason = str(drained.args[0]) if drained.args else "shutdown"
            if drain_reason == "pause":
                await self._set_run(run.id, RunStatus.PAUSED, event="run_paused")
                await self._finish(task, "succeeded")
            elif drain_reason == "cancel":
                await self._set_run(run.id, RunStatus.CANCELLED, event="run_cancelled")
                await self._finish(task, "cancelled")
            else:  # graceful shutdown: another worker resumes from the checkpoint
                await self._set_run(
                    run.id,
                    RunStatus.PENDING,
                    event="run_requeued",
                    payload={"message": "Worker restarting; will resume."},
                )
                await self._requeue(task, 0, "Worker shut down", refund=True)
        except asyncio.CancelledError:
            reason = flight.cancel_reason
            if reason == "cancel":
                await self._set_run(run.id, RunStatus.CANCELLED, event="run_cancelled")
                await self._finish(task, "cancelled")
            elif reason in ("shutdown", "lease_lost"):
                if reason == "shutdown":
                    await self._set_run(run.id, RunStatus.PENDING, event="run_requeued")
                    await self._requeue(task, 0, "Worker shut down", refund=True)
            else:
                raise
        except (StepBudgetExceeded, TokenBudgetExceeded) as exc:
            await self._set_run(run.id, RunStatus.FAILED, event="run_failed", error=str(exc))
            await self._finish(task, "failed", str(exc))
        except UncertainOutcome as exc:
            await self._set_run(run.id, RunStatus.FAILED, event="run_failed", error=str(exc)[:1000])
            await self._finish(task, "failed", str(exc))
        except TRANSIENT_ERRORS:
            msg = "A temporary problem (a database or network hiccup)"
            if task.attempt < task.max_attempts:
                delay = queue.backoff_s(task.attempt) + random.uniform(0, 2)  # noqa: S311
                await self._set_run(
                    run.id,
                    RunStatus.PENDING,
                    event="run_retry_scheduled",
                    payload={
                        "message": f"{msg}. Retrying in {delay:.0f} s.",
                        "attempt": task.attempt,
                    },
                )
                await self._requeue(task, delay, msg, refund=False)
            else:
                await self._set_run(run.id, RunStatus.FAILED, event="run_failed", error=msg)
                await self._finish(task, "failed", msg)
        except Exception as exc:  # noqa: BLE001 - any node error fails the run, never the worker
            msg = user_message(exc, where=f"run:{run.kind}")
            log.warning("run_failed", run=str(run.id), error=type(exc).__name__)
            await self._set_run(run.id, RunStatus.FAILED, event="run_failed", error=msg)
            await self._finish(task, "failed", msg)

    def _step_counter(self, run_id: uuid.UUID, flight: InFlight) -> Any:
        async def on_step(node: str, status: str) -> None:
            async with self.system_sessions() as s, s.begin():
                run = await s.get(WorkflowRun, run_id, with_for_update=True)
                if run is None:
                    return
                run.steps_completed += 1
                run.current_node = node
                over = run.steps_completed > run.step_budget
                control = run.control_request
                budget = run.step_budget
            # Honour pause/cancel at every step boundary (also covered by the heartbeat).
            if control == "pause":
                flight.control.request_drain("pause")
            elif control == "cancel":
                flight.control.request_drain("cancel")
            if over:
                raise StepBudgetExceeded(
                    f"This run exceeded its limit of {budget} steps and was stopped."
                )

        return on_step
