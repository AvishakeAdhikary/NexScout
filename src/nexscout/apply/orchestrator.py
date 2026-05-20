"""Apply orchestrator — acquire, worker loop, result handling (§5 + §13).

The atomic acquire query is the cornerstone of multi-worker safety:

* ``BEGIN IMMEDIATE`` locks the DB for write before SELECT.
* The same transaction SELECTs the highest-fit eligible job and UPDATEs its
  ``apply_status`` to ``'in_progress'`` with the worker's ``agent_id``.
* On COMMIT another worker cannot grab the same row.

``mark_result`` interprets the agent's ``RESULT:`` line, bumps
``apply_attempts``, and freezes the row at 99 when the reason is permanent.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.bundle import bundle_dir_for
from ..core.database import is_permanent_failure, transaction
from ..core.profile import Profile
from .policy import ApplyPolicy, load_policy
from .result_codes import RESULT_APPLIED, RESULT_CAPTCHA, RESULT_EXPIRED, RESULT_LOGIN_ISSUE

if TYPE_CHECKING:
    from ..captcha.base import CaptchaSolver
    from ..llm.router import LLMRouter
    from .dashboard import LiveDashboard

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Atomic acquire
# ---------------------------------------------------------------------------


@dataclass
class AcquireOptions:
    """Configuration for the atomic acquire query."""

    agent_id: str
    max_attempts: int
    min_score: int
    blocked_sites: list[str]
    blocked_url_patterns: list[str]


def _build_acquire_sql(opts: AcquireOptions) -> tuple[str, list[Any]]:
    site_clause = ""
    site_params: list[Any] = []
    if opts.blocked_sites:
        placeholders = ",".join("?" for _ in opts.blocked_sites)
        site_clause = f" AND (site IS NULL OR site NOT IN ({placeholders}))"
        site_params.extend(opts.blocked_sites)

    url_clauses: list[str] = []
    url_params: list[Any] = []
    for pat in opts.blocked_url_patterns:
        url_clauses.append("url NOT LIKE ?")
        url_params.append(pat)
    url_clause = (" AND " + " AND ".join(url_clauses)) if url_clauses else ""

    sql = (
        "SELECT rowid AS id, url, title, site, application_url, "
        "tailored_resume_path, fit_score, location, full_description, "
        "cover_letter_path "
        "FROM jobs "
        "WHERE tailored_resume_path IS NOT NULL "
        "  AND (apply_status IS NULL OR apply_status = 'failed') "
        "  AND (apply_attempts IS NULL OR apply_attempts < ?) "
        "  AND fit_score >= ? "
        f"{site_clause}"
        f"{url_clause} "
        "ORDER BY fit_score DESC, url "
        "LIMIT 1"
    )
    return sql, [opts.max_attempts, opts.min_score, *site_params, *url_params]


def acquire_job(profile: Profile, conn: sqlite3.Connection, *, agent_id: str) -> dict[str, Any] | None:
    """Atomic SELECT/UPDATE per §5. Returns the job row dict or ``None``."""
    policy = load_policy()
    opts = AcquireOptions(
        agent_id=agent_id,
        max_attempts=int(profile.apply.max_attempts or 3),
        min_score=int(profile.search.min_score or 7),
        blocked_sites=list(policy.blocked_sites),
        blocked_url_patterns=list(policy.blocked_url_patterns),
    )
    sql, params = _build_acquire_sql(opts)
    with transaction(conn):
        row = conn.execute(sql, params).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET apply_status='in_progress', agent_id=?, last_attempted_at=? WHERE url=?",
            (agent_id, _ts(), row["url"]),
        )
        return dict(row)


# ---------------------------------------------------------------------------
# Result marking
# ---------------------------------------------------------------------------


def mark_result(
    job_url: str,
    result_code: str,
    reason: str | None,
    conn: sqlite3.Connection,
    *,
    duration_ms: int | None = None,
    cost_usd: float | None = None,
    captcha_solved: bool | None = None,
    bundle_dir: str | None = None,
) -> None:
    """Persist the agent's terminal status and bump ``apply_attempts``."""
    code = (result_code or "").upper()
    status = _status_for_code(code)
    permanent = code.startswith("FAILED") and is_permanent_failure(reason)
    if code in {RESULT_CAPTCHA, RESULT_EXPIRED, RESULT_LOGIN_ISSUE}:
        permanent = True

    attempts_bump = 99 if permanent else 1
    applied_now = code == RESULT_APPLIED
    now = _ts()
    sets: list[str] = [
        "apply_status=?",
        "apply_error=?",
        "applied_at=CASE WHEN ? THEN ? ELSE applied_at END",
        "apply_attempts=COALESCE(apply_attempts,0)+?",
    ]
    params: list[Any] = [status, reason, 1 if applied_now else 0, now, attempts_bump]

    if duration_ms is not None:
        sets.append("apply_duration_ms=?")
        params.append(int(duration_ms))
    if cost_usd is not None:
        sets.append("cost_usd=COALESCE(cost_usd,0)+?")
        params.append(float(cost_usd))
    if captcha_solved is not None:
        sets.append("captcha_solved=?")
        params.append(1 if captcha_solved else 0)
    if bundle_dir is not None:
        sets.append("bundle_dir=?")
        params.append(bundle_dir)

    params.append(job_url)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE url=?", params)


def _status_for_code(code: str) -> str:
    if code == RESULT_APPLIED:
        return "applied"
    if code == RESULT_EXPIRED:
        return "expired"
    if code == RESULT_CAPTCHA:
        return "captcha"
    if code == RESULT_LOGIN_ISSUE:
        return "login_issue"
    return "failed"


def release_lock(job_url: str, conn: sqlite3.Connection, *, agent_id: str) -> None:
    """Reset ``apply_status`` to NULL if it's still ``in_progress`` for ``agent_id``."""
    conn.execute(
        "UPDATE jobs SET apply_status=NULL WHERE url=? AND apply_status='in_progress' AND agent_id=?",
        (job_url, agent_id),
    )


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

#: A callable that, given (job, profile, bundle_dir, driver, solver, router),
#: returns ``(result_code, reason, cost_usd, captcha_solved)``. The default
#: is :func:`apply.agent.run_agent` but tests/backends can inject their own.
ApplyRunner = Callable[..., tuple[str, str | None, float, bool]]


def _default_runner() -> ApplyRunner:
    from .agent import run_agent

    return run_agent


def worker_loop(
    worker_id: int,
    profile: Profile,
    db_conn: sqlite3.Connection,
    solver: CaptchaSolver | None,
    llm_router: LLMRouter,
    *,
    pool: Any | None = None,
    runner: ApplyRunner | None = None,
    dashboard: LiveDashboard | None = None,
    limit: int = 0,
    dry_run: bool = False,
    backend: str = "native",
    poll_interval: float = 10.0,
    continuous: bool = False,
) -> int:
    """Run one worker thread: acquire → run agent → mark_result → loop.

    Returns the number of jobs the worker processed.
    """
    agent_id = f"worker-{worker_id}"
    runner = runner or _default_runner()
    applied = 0
    while True:
        if 0 < limit <= applied:
            break
        job = acquire_job(profile, db_conn, agent_id=agent_id)
        if job is None:
            if not continuous:
                break
            time.sleep(poll_interval)
            continue

        bundle_dir = bundle_dir_for(int(job["id"]))
        start = time.monotonic()
        driver: Any = None
        if dashboard:
            dashboard.start_job(worker_id, job)
        try:
            if pool is not None:
                driver = pool.acquire(worker_id)
            code, reason, cost, solved = runner(
                job=job,
                profile=profile,
                bundle_dir=bundle_dir,
                driver=driver,
                solver=solver,
                router=llm_router,
                dry_run=dry_run,
                dashboard=dashboard,
                worker_id=worker_id,
            )
        except Exception as e:
            log.exception("worker %d crashed on %s", worker_id, job.get("url"))
            release_lock(job["url"], db_conn, agent_id=agent_id)
            if dashboard:
                dashboard.finish_job(worker_id, "FAILED", reason=str(e))
            if not continuous:
                break
            continue
        finally:
            if pool is not None and driver is not None:
                with _suppress():
                    pool.release(worker_id, driver)

        duration_ms = int((time.monotonic() - start) * 1000)
        mark_result(
            job["url"],
            code,
            reason,
            db_conn,
            duration_ms=duration_ms,
            cost_usd=cost,
            captcha_solved=solved,
            bundle_dir=str(bundle_dir),
        )
        if dashboard:
            dashboard.finish_job(worker_id, code, reason=reason)
        # Persist final result.json into bundle.
        try:
            (bundle_dir / "result.json").write_text(
                _result_json(code, reason, duration_ms, cost, solved, agent_id, backend),
                encoding="utf-8",
            )
        except OSError as e:
            log.warning("could not write result.json: %s", e)
        applied += 1
    return applied


def _result_json(
    code: str,
    reason: str | None,
    duration_ms: int,
    cost: float,
    solved: bool,
    agent_id: str,
    backend: str,
) -> str:
    import json

    return json.dumps(
        {
            "code": code,
            "reason": reason,
            "duration_ms": duration_ms,
            "cost_usd": cost,
            "captcha_solved": bool(solved),
            "agent_id": agent_id,
            "backend": backend,
            "ts": _ts(),
        },
        indent=2,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _suppress:
    def __enter__(self) -> _suppress:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None


__all__ = [
    "AcquireOptions",
    "ApplyPolicy",
    "ApplyRunner",
    "Path",  # re-exported for ergonomic typing in callers
    "acquire_job",
    "mark_result",
    "release_lock",
    "worker_loop",
]
