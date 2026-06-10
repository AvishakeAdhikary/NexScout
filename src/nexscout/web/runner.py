"""Background task runner for long web actions (the "Check for new jobs" run).

The CLI ``tick`` (discover → enrich → score → tailor → apply) can take
minutes. Running it inside a request handler freezes the browser, so we run
it in a daemon thread and expose a tiny status object the UI can poll.

State is kept in-memory (process-local) and mirrored to a small JSON file
under ``~/.nexscout/`` so a dashboard reload after a restart still shows the
last result.

The public surface is intentionally tiny:

* :func:`start_run` — kick off the run in a background thread (no-op if one
  is already in flight); returns the current :class:`RunStatus`.
* :func:`get_status` — read the current status (for the polling endpoint).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from ..core.config import nexscout_dir

#: Filename for the persisted status mirror.
_STATUS_FILE = "run-status.json"

#: Guards ``_STATUS`` and the "is a run already in flight" decision.
_LOCK = threading.Lock()


@dataclass
class RunStatus:
    """Snapshot of the background run, safe to JSON-serialize for the UI."""

    running: bool = False
    started_at: str | None = None
    last_finished: str | None = None
    summary: dict[str, Any] | None = None
    error: str | None = None
    #: Plain-language one-liner the UI shows verbatim.
    message: str = "NexScout has not run a check yet."

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Process-local current status.
_STATUS = RunStatus()


def _status_path():
    return nexscout_dir() / _STATUS_FILE


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _persist(status: RunStatus) -> None:
    """Best-effort mirror of the status to disk (never raises into the UI)."""
    with suppress(OSError):
        _status_path().write_text(json.dumps(status.to_dict()), encoding="utf-8")


def _load_persisted() -> RunStatus | None:
    """Load the last persisted status (used after a process restart)."""
    p = _status_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    status = RunStatus()
    status.running = False  # a freshly-loaded process is never mid-run.
    status.started_at = data.get("started_at")
    status.last_finished = data.get("last_finished")
    status.summary = data.get("summary")
    status.error = data.get("error")
    status.message = data.get("message") or status.message
    return status


def _summarize(summary: dict[str, Any]) -> str:
    """Turn the tick summary dict into one friendly sentence."""
    if not isinstance(summary, dict):
        return "Check finished."
    discovered = summary.get("discovered", 0)
    applied = summary.get("applied", 0)
    questions = summary.get("questions_surfaced", summary.get("questions", 0))
    parts: list[str] = []
    if discovered:
        parts.append(f"found {discovered} new job{'s' if discovered != 1 else ''}")
    if applied:
        parts.append(f"applied to {applied}")
    if questions:
        parts.append(f"{questions} need{'s' if questions == 1 else ''} your answer")
    if not parts:
        return "Check finished — nothing new this time."
    return "Done: " + ", ".join(parts) + "."


def _default_tick() -> dict[str, Any]:
    """Run the real tick. Imported lazily so tests can patch it cheaply."""
    from ..core.profile import Profile
    from ..openclaw.tick import run as tick_run

    profile = Profile.from_path()
    return tick_run(profile=profile)


def _runner(work: Callable[[], dict[str, Any]]) -> None:
    """Thread body: run ``work`` and record the outcome."""
    try:
        summary = work()
        with _LOCK:
            _STATUS.running = False
            _STATUS.last_finished = _now()
            _STATUS.summary = summary if isinstance(summary, dict) else {"result": summary}
            _STATUS.error = None
            _STATUS.message = _summarize(_STATUS.summary)
            _persist(_STATUS)
        _write_last_tick(summary)
    except Exception as exc:  # never let the thread die silently.
        with _LOCK:
            _STATUS.running = False
            _STATUS.last_finished = _now()
            _STATUS.error = str(exc)
            _STATUS.message = "Something went wrong during the check. See details below."
            _persist(_STATUS)


def _write_last_tick(summary: Any) -> None:
    """Mirror the old ``last-tick.json`` marker the dashboard reads."""
    try:
        from ..core.profile import Profile

        channel: str | None = None
        try:
            channel = Profile.from_path().openclaw.channel
        except Exception:
            channel = None
        marker = nexscout_dir() / "last-tick.json"
        marker.write_text(
            json.dumps({"ts": _now(), "channel": channel, "summary": summary}),
            encoding="utf-8",
        )
    except OSError:
        pass


def start_run(work: Callable[[], dict[str, Any]] | None = None) -> RunStatus:
    """Start the background run if one isn't already in flight.

    Returns the current :class:`RunStatus` (which will have ``running=True``
    when this call actually started a fresh run).
    """
    work = work or _default_tick
    with _LOCK:
        if _STATUS.running:
            return RunStatus(**_STATUS.to_dict())
        _STATUS.running = True
        _STATUS.started_at = _now()
        _STATUS.error = None
        _STATUS.message = "Checking for new jobs now… this can take a few minutes."
        _persist(_STATUS)
        snapshot = RunStatus(**_STATUS.to_dict())

    thread = threading.Thread(target=_runner, args=(work,), daemon=True, name="nexscout-tick")
    thread.start()
    return snapshot


def get_status() -> RunStatus:
    """Return a copy of the current run status (loading from disk if fresh)."""
    with _LOCK:
        if not _STATUS.running and _STATUS.last_finished is None and _STATUS.started_at is None:
            persisted = _load_persisted()
            if persisted is not None:
                return persisted
        return RunStatus(**_STATUS.to_dict())


__all__ = ["RunStatus", "get_status", "start_run"]
