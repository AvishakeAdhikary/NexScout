"""Cross-process pipeline status, control, and the per-job stage-lock.

The autopilot, the web UI, and the MCP server run as **separate processes**
(separate Docker containers) that share only the filesystem. This module is
their common channel, via two atomic JSON files in the config dir:

* ``pipeline-status.json`` — live per-stage progress of the current/last pass.
  Written by whatever runs a pass (the autopilot tick, or a manual web/MCP run);
  read by the UI/MCP to draw the progress panel.
* ``pipeline-control.json`` — ``paused`` flag, a one-shot ``stop_requested``, and
  per-stage on/off switches. Written by the UI/MCP; read by the autopilot
  between/within stages so the user's intent actually takes effect.

Writes are atomic (temp file + ``os.replace``) so a reader never sees a partial
file, and the temp name carries the PID so two writers can't clobber each other.

:func:`eligible_stage` computes the single stage one job row is currently
eligible for — mirroring each stage's SQL predicate — so the UI/MCP honour the
exact same gating ("stage-lock") the autopilot does.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import nexscout_dir

#: Ordered per-job pipeline stages (the stage-lock timeline). ``render`` runs
#: automatically right before apply, so it is shown in the pipeline panel but is
#: not offered as a separate per-job action.
STAGES: tuple[str, ...] = ("discover", "enrich", "score", "tailor", "cover", "render", "apply")

#: Stages a user can run for a single job (render is folded into apply).
PER_JOB_STAGES: tuple[str, ...] = ("enrich", "score", "tailor", "apply")

#: Everything the autopilot steps through in one pass (``questions`` is the
#: housekeeping step that surfaces unanswered questions to the channel).
ALL_STEPS: tuple[str, ...] = (*STAGES, "questions")

_STATUS_FILE = "pipeline-status.json"
_CONTROL_FILE = "pipeline-control.json"

_ENRICH_SKIP_SITES = {"glassdoor", "google", "Workopolis"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _path(name: str) -> Path:
    return nexscout_dir() / name


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Control (written by UI/MCP, read by the autopilot)
# --------------------------------------------------------------------------- #


def read_control() -> dict[str, Any]:
    """Return the control record with defaults filled in."""
    c = _read_json(_path(_CONTROL_FILE))
    raw = c.get("disabled_stages", [])
    disabled = [s for s in raw if isinstance(s, str) and s in ALL_STEPS] if isinstance(raw, list) else []
    return {
        "paused": bool(c.get("paused", False)),
        "stop_requested": bool(c.get("stop_requested", False)),
        "disabled_stages": disabled,
    }


def _write_control(c: dict[str, Any]) -> None:
    _write_json(_path(_CONTROL_FILE), c)


def set_paused(paused: bool) -> dict[str, Any]:
    c = read_control()
    c["paused"] = bool(paused)
    _write_control(c)
    return c


def is_paused() -> bool:
    return bool(read_control()["paused"])


def request_stop() -> None:
    c = read_control()
    c["stop_requested"] = True
    _write_control(c)


def clear_stop() -> None:
    c = read_control()
    c["stop_requested"] = False
    _write_control(c)


def stop_requested() -> bool:
    return bool(read_control()["stop_requested"])


def set_stage_enabled(stage: str, enabled: bool) -> dict[str, Any]:
    c = read_control()
    disabled = set(c["disabled_stages"])
    if enabled:
        disabled.discard(stage)
    elif stage in ALL_STEPS:
        disabled.add(stage)
    c["disabled_stages"] = sorted(disabled)
    _write_control(c)
    return c


def stage_enabled(stage: str) -> bool:
    return stage not in read_control()["disabled_stages"]


# --------------------------------------------------------------------------- #
# Status (written by whoever runs a pass, read by UI/MCP)
# --------------------------------------------------------------------------- #


def _blank_status() -> dict[str, Any]:
    return {
        "running": False,
        "source": None,
        "current_stage": None,
        "pass_started_at": None,
        "updated_at": _now(),
        "stages": {s: {"state": "idle", "done": 0, "total": 0} for s in ALL_STEPS},
        "last_summary": None,
        "last_finished": None,
        "aborted": False,
    }


def read_status() -> dict[str, Any]:
    """Return the live status, always with every stage key present."""
    s = _read_json(_path(_STATUS_FILE))
    base = _blank_status()
    if not s:
        return base
    base.update(s)
    stages = base.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    for st in ALL_STEPS:
        if not isinstance(stages.get(st), dict):
            stages[st] = {"state": "idle", "done": 0, "total": 0}
    base["stages"] = stages
    return base


def begin_pass(source: str, *, disabled: list[str] | None = None) -> None:
    s = _blank_status()
    s["running"] = True
    s["source"] = source
    s["pass_started_at"] = _now()
    dis = disabled or []
    for st in ALL_STEPS:
        s["stages"][st]["state"] = "disabled" if st in dis else "pending"
    _write_json(_path(_STATUS_FILE), s)


def stage_state(stage: str, state: str, *, done: int = 0, total: int = 0) -> None:
    """Set a stage's coarse state (running/done/skipped/error/disabled)."""
    s = read_status()
    s["running"] = True
    if state == "running":
        s["current_stage"] = stage
    st = s["stages"].setdefault(stage, {"state": "idle", "done": 0, "total": 0})
    st["state"] = state
    st["done"] = int(done)
    st["total"] = int(total)
    s["updated_at"] = _now()
    _write_json(_path(_STATUS_FILE), s)


def stage_progress(stage: str, done: int, total: int) -> None:
    """Update the live done/total counter for a running stage (per item)."""
    s = read_status()
    st = s["stages"].setdefault(stage, {"state": "running", "done": 0, "total": 0})
    st["state"] = "running"
    st["done"] = int(done)
    st["total"] = int(total)
    s["running"] = True
    s["current_stage"] = stage
    s["updated_at"] = _now()
    _write_json(_path(_STATUS_FILE), s)


def end_pass(summary: dict[str, Any] | None, *, aborted: bool = False) -> None:
    s = read_status()
    s["running"] = False
    s["current_stage"] = None
    s["last_summary"] = summary
    s["last_finished"] = _now()
    s["aborted"] = bool(aborted)
    s["updated_at"] = _now()
    for st in s["stages"].values():
        if isinstance(st, dict) and st.get("state") in ("pending", "running"):
            st["state"] = "stopped" if aborted else "idle"
    _write_json(_path(_STATUS_FILE), s)


# --------------------------------------------------------------------------- #
# Stage-lock — the single stage a given job is eligible for
# --------------------------------------------------------------------------- #


def eligible_stage(job: dict[str, Any], *, min_score: int) -> str | None:
    """Return the one stage ``job`` is currently eligible for, or None.

    Mirrors the SQL predicates of each stage so the UI/MCP enforce the exact
    same gating as the autopilot. ``render`` is folded into ``apply`` (it runs
    automatically), so the returned value is one of :data:`PER_JOB_STAGES` or
    None (terminal, not-a-match, or waiting on the user).
    """
    apply_status = job.get("apply_status")
    if apply_status in ("applied", "in_progress", "paused_for_question", "captcha", "captcha_manual"):
        return None

    detail_scraped = job.get("detail_scraped_at")
    site = job.get("site") or ""
    if detail_scraped is None and site not in _ENRICH_SKIP_SITES:
        return "enrich"

    full_desc = job.get("full_description")
    fit = job.get("fit_score")
    if full_desc is not None and fit is None:
        return "score"

    tailored = job.get("tailored_resume_path")
    tailor_attempts = int(job.get("tailor_attempts") or 0)
    apply_attempts = int(job.get("apply_attempts") or 0)
    if fit is not None:
        if int(fit) < int(min_score):
            return None  # scored below the cutoff — not a match
        if not tailored and tailor_attempts < 5:
            return "tailor"

    if tailored and (apply_status is None or apply_status == "failed") and apply_attempts < 99:
        return "apply"
    return None


def backlog_counts(conn: sqlite3.Connection, *, min_score: int, always_cover: bool) -> dict[str, int]:
    """How many jobs are currently waiting at the head of each stage's queue.

    The predicates mirror each stage's SQL exactly, so the numbers match what
    the next pass will actually pick up.
    """

    def _count(where: str, params: tuple[Any, ...] = ()) -> int:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM jobs WHERE {where}", params).fetchone()
        return int(row["n"]) if row is not None else 0

    always = 1 if always_cover else 0
    return {
        "enrich": _count("detail_scraped_at IS NULL AND site NOT IN ('glassdoor','google','Workopolis')"),
        "score": _count("full_description IS NOT NULL AND fit_score IS NULL"),
        "tailor": _count(
            "fit_score >= ? AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts,0) < 5",
            (min_score,),
        ),
        "cover": _count(
            "tailored_resume_path IS NOT NULL AND cover_letter_path IS NULL "
            "AND COALESCE(cover_attempts,0) < 3 AND (cover_required = 1 OR ? = 1)",
            (always,),
        ),
        "apply": _count(
            "tailored_resume_path IS NOT NULL AND (apply_status IS NULL OR apply_status='failed') "
            "AND COALESCE(apply_attempts,0) < 99"
        ),
    }


__all__ = [
    "ALL_STEPS",
    "PER_JOB_STAGES",
    "STAGES",
    "backlog_counts",
    "begin_pass",
    "clear_stop",
    "eligible_stage",
    "end_pass",
    "is_paused",
    "read_control",
    "read_status",
    "request_stop",
    "set_paused",
    "set_stage_enabled",
    "stage_enabled",
    "stage_progress",
    "stage_state",
    "stop_requested",
]
