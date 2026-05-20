"""Rich live dashboard for the apply orchestrator (§13.6 of plan.md).

A single :class:`LiveDashboard` instance is shared across all workers. Each
worker mutates a :class:`WorkerState` via the helpers below; the dashboard
refreshes at 2 Hz.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

#: Status palette per §13.6.
STATUS_PALETTE: dict[str, str] = {
    "starting": "dim",
    "idle": "dim",
    "applying": "yellow",
    "applied": "bold green",
    "failed": "red",
    "expired": "dim red",
    "captcha": "magenta",
    "login_issue": "red",
    "sso_required": "red",
    "done": "bold",
}


@dataclass
class WorkerState:
    """Per-worker mutable status (§13.6 dataclass)."""

    worker_id: int
    status: str = "idle"
    job_title: str = ""
    company: str = ""
    score: int = 0
    start_time: float | None = None
    actions: int = 0
    last_action: str = ""
    jobs_applied: int = 0
    jobs_failed: int = 0
    total_cost: float = 0.0

    def elapsed_str(self) -> str:
        if not self.start_time:
            return "—"
        secs = int(time.monotonic() - self.start_time)
        return f"{secs // 60}m{secs % 60:02d}s" if secs >= 60 else f"{secs}s"


class LiveDashboard:
    """Rich-Live wrapper coordinating multi-worker status + events panel."""

    def __init__(self, workers: int, *, console: Console | None = None, refresh_hz: float = 2.0) -> None:
        self.workers: dict[int, WorkerState] = {w: WorkerState(worker_id=w) for w in range(workers)}
        self._events: deque[str] = deque(maxlen=8)
        self._lock = threading.Lock()
        self._console = console or Console()
        self._refresh_hz = refresh_hz
        self._live: Live | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> LiveDashboard:
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=self._refresh_hz,
            transient=False,
        )
        self._live.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._live is not None:
            self._live.__exit__(exc_type, exc, tb)
            self._live = None

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_event(self, text: str, *, worker_id: int | None = None) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        suffix = f" [W{worker_id}]" if worker_id is not None else ""
        with self._lock:
            self._events.appendleft(f"[{ts}]{suffix} {text}")
        self._refresh()

    def start_job(self, worker_id: int, job: dict[str, Any]) -> None:
        with self._lock:
            state = self.workers.setdefault(worker_id, WorkerState(worker_id=worker_id))
            state.status = "starting"
            state.job_title = str(job.get("title") or "")[:40]
            state.company = str(job.get("site") or "")[:25]
            state.score = int(job.get("fit_score") or 0)
            state.start_time = time.monotonic()
            state.actions = 0
            state.last_action = "acquire"
        self.add_event(f"Start: {job.get('title') or ''}", worker_id=worker_id)

    def tick_action(self, worker_id: int, name: str) -> None:
        with self._lock:
            state = self.workers.setdefault(worker_id, WorkerState(worker_id=worker_id))
            state.status = "applying"
            state.actions += 1
            state.last_action = name
        self._refresh()

    def finish_job(self, worker_id: int, code: str, *, reason: str | None = None) -> None:
        with self._lock:
            state = self.workers.setdefault(worker_id, WorkerState(worker_id=worker_id))
            up = code.upper()
            if up == "APPLIED":
                state.status = "applied"
                state.jobs_applied += 1
            elif up == "EXPIRED":
                state.status = "expired"
                state.jobs_failed += 1
            elif up == "CAPTCHA":
                state.status = "captcha"
                state.jobs_failed += 1
            elif up == "LOGIN_ISSUE":
                state.status = "login_issue"
                state.jobs_failed += 1
            else:
                state.status = "failed"
                state.jobs_failed += 1
        suffix = f" — {reason}" if reason else ""
        self.add_event(f"Done: {code}{suffix}", worker_id=worker_id)

    def add_cost(self, worker_id: int, delta: float) -> None:
        with self._lock:
            state = self.workers.setdefault(worker_id, WorkerState(worker_id=worker_id))
            state.total_cost += float(delta)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._render())

    def _render(self) -> Group:
        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("W", width=3)
        table.add_column("Job", overflow="fold")
        table.add_column("Status", width=14)
        table.add_column("Time", width=8)
        table.add_column("Acts", width=5)
        table.add_column("Last Action", overflow="fold")
        table.add_column("OK", width=4)
        table.add_column("Fail", width=5)
        table.add_column("Cost", width=8)

        for w in sorted(self.workers):
            state = self.workers[w]
            colour = STATUS_PALETTE.get(state.status, "white")
            job_descr = (
                f"{state.job_title} @ {state.company}"
                if state.job_title
                else "(idle)"
            )
            table.add_row(
                str(w),
                job_descr,
                f"[{colour}]{state.status}[/{colour}]",
                state.elapsed_str(),
                str(state.actions),
                state.last_action or "",
                str(state.jobs_applied),
                str(state.jobs_failed),
                f"${state.total_cost:.3f}",
            )

        events_text = "\n".join(self._events) if self._events else "(no events yet)"
        events = Panel(events_text, title="Recent Events", border_style="dim")
        return Group(table, events)


__all__ = ["STATUS_PALETTE", "LiveDashboard", "WorkerState"]
