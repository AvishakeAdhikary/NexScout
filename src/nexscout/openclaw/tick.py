"""``nexscout tick`` — bounded unit of work per §18.

Steps (each capped by ``profile.openclaw.tick_budget``):

1. Pull ≤10 new jobs from each discovery engine.
2. Enrich up to 20 pending.
3. Score up to 50 pending.
4. Tailor up to 5 high-fit.
5. Render any missing PDFs.
6. Apply to up to 3 jobs.
7. Surface pending_questions to OpenClaw inbox.
8. Print a one-line summary.

Each stage is wrapped in a soft time budget; we never exceed the per-stage
limits even if the wall-clock budget allows. Stages catch and log exceptions
so a failure in one doesn't tank the rest.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.config import database_path, nexscout_dir
from ..core.database import init_db
from ..core.profile import Profile

log = logging.getLogger(__name__)


@dataclass
class TickSummary:
    """Per-stage counters returned from :func:`run`."""

    discovered: int = 0
    enriched: int = 0
    scored: int = 0
    tailored: int = 0
    rendered: int = 0
    applied: int = 0
    questions_surfaced: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0

    def to_one_liner(self) -> str:
        return (
            f"tick: discovered={self.discovered} enriched={self.enriched} "
            f"scored={self.scored} tailored={self.tailored} rendered={self.rendered} "
            f"applied={self.applied} questions={self.questions_surfaced} "
            f"errors={len(self.errors)} ({self.duration_s:.1f}s)"
        )


def _ts() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Stage runner — wraps a callable in error-catching + soft time budget
# ---------------------------------------------------------------------------


def _run_stage(
    name: str,
    fn: Any,
    *,
    summary: TickSummary,
    deadline: float | None = None,
) -> Any:
    """Invoke ``fn``; record errors in the summary. Returns the callable result or 0."""
    if deadline is not None and time.monotonic() > deadline:
        log.info("tick: skipping %s (out of budget)", name)
        return None
    try:
        return fn()
    except Exception as e:
        log.exception("tick stage %s failed", name)
        summary.errors.append(f"{name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Public entry — used by the CLI ``nexscout tick`` command
# ---------------------------------------------------------------------------


#: Soft wall-clock cap per §18 (≈5 min). Stages still respect their own caps.
DEFAULT_WALL_CLOCK_S = 300.0


def run(
    *,
    profile: Profile,
    db: sqlite3.Connection | None = None,
    wall_clock_s: float = DEFAULT_WALL_CLOCK_S,
    stages: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Run a single tick. Returns the summary dict."""
    summary = TickSummary(started_at=_ts())
    started = time.monotonic()
    deadline = started + max(0.0, float(wall_clock_s))
    conn = db if db is not None else init_db(database_path())
    budget = profile.openclaw.tick_budget

    stage_set = set(stages) if stages else {
        "discover", "enrich", "score", "tailor", "render", "apply", "questions"
    }

    if "discover" in stage_set:
        summary.discovered = _run_stage(
            "discover",
            lambda: _stage_discover(profile, conn, budget.discover_per_engine),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "enrich" in stage_set:
        summary.enriched = _run_stage(
            "enrich",
            lambda: _stage_enrich(profile, conn, budget.enrich),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "score" in stage_set:
        summary.scored = _run_stage(
            "score",
            lambda: _stage_score(profile, conn, budget.score),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "tailor" in stage_set:
        summary.tailored = _run_stage(
            "tailor",
            lambda: _stage_tailor(profile, conn, budget.tailor),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "render" in stage_set:
        summary.rendered = _run_stage(
            "render",
            lambda: _stage_render(profile, conn),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "apply" in stage_set:
        summary.applied = _run_stage(
            "apply",
            lambda: _stage_apply(profile, conn, budget.apply),
            summary=summary,
            deadline=deadline,
        ) or 0
    if "questions" in stage_set:
        summary.questions_surfaced = _run_stage(
            "questions",
            lambda: _stage_surface_questions(profile, conn),
            summary=summary,
            deadline=deadline,
        ) or 0

    summary.finished_at = _ts()
    summary.duration_s = time.monotonic() - started
    print(summary.to_one_liner())
    return asdict(summary)


# ---------------------------------------------------------------------------
# Stage implementations — keep tiny & test-friendly
# ---------------------------------------------------------------------------


def _stage_discover(profile: Profile, conn: sqlite3.Connection, per_engine_limit: int) -> int:
    """Pull at most ``per_engine_limit`` jobs per discovery engine."""
    from ..llm.budget import BudgetLedger
    from ..llm.router import LLMRouter
    from ..pipeline import run_discover_stage

    router: LLMRouter | None
    try:
        router = LLMRouter(
            profile,
            budget=BudgetLedger(
                monthly_usd=profile.llm.budgets.monthly_usd,
                daily_calls=profile.llm.budgets.daily_calls,
            ),
        )
    except Exception as e:
        log.warning("tick: cannot build router for discover (%s); running without smartextract", e)
        router = None
    return run_discover_stage(
        conn=conn,
        profile=profile,
        router=router,
        limit_per_engine=per_engine_limit,
    )


def _stage_enrich(profile: Profile, conn: sqlite3.Connection, limit: int) -> int:
    """Enrich up to ``limit`` pending rows.

    Returns the number of jobs that got a ``full_description`` written.
    """
    from ..llm.budget import BudgetLedger
    from ..llm.router import LLMRouter
    from ..pipeline import run_enrich_stage

    try:
        from ..browser.driver import UndetectedFactory

        factory = UndetectedFactory()
    except Exception as e:
        log.info("tick: no browser available for enrich (%s); skipping", e)
        return 0

    try:
        router: LLMRouter | None = LLMRouter(
            profile,
            budget=BudgetLedger(
                monthly_usd=profile.llm.budgets.monthly_usd,
                daily_calls=profile.llm.budgets.daily_calls,
            ),
        )
    except Exception as e:
        log.warning("tick: cannot build router for enrich (%s)", e)
        router = None

    return run_enrich_stage(
        conn=conn,
        profile=profile,
        router=router,
        browser_factory=factory,
        limit=limit,
    )


def _stage_score(profile: Profile, conn: sqlite3.Connection, limit: int) -> int:
    """Score up to ``limit`` pending rows via the LLM router."""
    from ..llm.budget import BudgetLedger
    from ..llm.router import LLMRouter
    from ..pipeline import run_score_stage

    router = LLMRouter(
        profile,
        budget=BudgetLedger(
            monthly_usd=profile.llm.budgets.monthly_usd,
            daily_calls=profile.llm.budgets.daily_calls,
        ),
    )
    return run_score_stage(conn=conn, router=router, profile=profile, limit=limit)


def _stage_tailor(profile: Profile, conn: sqlite3.Connection, limit: int) -> int:
    from ..llm.budget import BudgetLedger
    from ..llm.router import LLMRouter
    from ..pipeline import run_tailor_stage

    router = LLMRouter(
        profile,
        budget=BudgetLedger(
            monthly_usd=profile.llm.budgets.monthly_usd,
            daily_calls=profile.llm.budgets.daily_calls,
        ),
    )
    return run_tailor_stage(conn=conn, router=router, profile=profile, limit=limit)


def _stage_render(profile: Profile, conn: sqlite3.Connection) -> int:
    from ..pipeline import run_render_stage

    return run_render_stage(conn=conn, profile=profile)


def _stage_apply(profile: Profile, conn: sqlite3.Connection, limit: int) -> int:
    """Apply to at most ``limit`` eligible jobs using a single-worker browser pool.

    The whole stack (browser pool, CAPTCHA solver, LLM router) is imported
    lazily so a tick on a host without these dependencies just logs and
    returns 0 rather than crashing.
    """
    eligible = conn.execute(
        "SELECT COUNT(*) AS n FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND (apply_status IS NULL OR apply_status='failed') "
        "AND (apply_attempts IS NULL OR apply_attempts < 99)"
    ).fetchone()
    if not eligible or int(eligible["n"]) == 0:
        return 0

    try:
        from ..apply.orchestrator import worker_loop
        from ..browser.pool import BrowserPool
        from ..captcha.capsolver import CapSolverSolver
        from ..llm.budget import BudgetLedger
        from ..llm.router import LLMRouter
    except ImportError as e:
        log.info("tick: apply backend unavailable (%s); skipping", e)
        return 0

    solver = CapSolverSolver(api_key=profile.captcha.api_key) if profile.captcha.api_key else None

    try:
        router = LLMRouter(
            profile,
            budget=BudgetLedger(
                monthly_usd=profile.llm.budgets.monthly_usd,
                daily_calls=profile.llm.budgets.daily_calls,
            ),
        )
    except Exception as e:
        log.warning("tick: cannot build router for apply (%s)", e)
        return 0

    try:
        pool = BrowserPool(workers=1, headless=True)
    except Exception as e:
        log.info("tick: no browser pool available for apply (%s); skipping", e)
        return 0

    try:
        return worker_loop(
            0,
            profile,
            conn,
            solver,
            router,
            pool=pool,
            limit=limit,
            dry_run=profile.apply.dry_run,
            continuous=False,
        )
    except Exception as e:
        log.warning("tick: apply worker_loop crashed (%s)", e)
        return 0
    finally:
        from contextlib import suppress

        with suppress(Exception):
            pool.close_all()


def _stage_surface_questions(profile: Profile, conn: sqlite3.Connection) -> int:
    """Write any newly-pending questions to ``~/.openclaw/inbox/nexscout-<ts>.md``."""
    _ = profile
    rows = conn.execute(
        "SELECT id, job_url, question, asked_at FROM pending_questions "
        "WHERE answered_at IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        return 0

    inbox = Path.home() / ".openclaw" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    fname = f"nexscout-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    payload = ["# NexScout: pending questions", ""]
    for r in rows:
        payload.append(f"## Q{r['id']} — {r['question']}")
        if r["job_url"]:
            payload.append(f"- job: {r['job_url']}")
        if r["asked_at"]:
            payload.append(f"- asked: {r['asked_at']}")
        payload.append("")
    (inbox / fname).write_text("\n".join(payload), encoding="utf-8")

    # Record an event so the dashboard shows it.
    conn.execute(
        "INSERT INTO events (ts, kind, payload_json) VALUES (?, 'tick', ?)",
        (_ts(), f'{{"questions_surfaced": {len(rows)}}}'),
    )

    # Persist a marker so the web UI's "Last tick" knows we ran.
    marker = nexscout_dir() / "last-tick.json"
    marker.write_text(
        f'{{"ts": "{_ts()}", "questions": {len(rows)}}}',
        encoding="utf-8",
    )
    return len(rows)


__all__ = ["DEFAULT_WALL_CLOCK_S", "TickSummary", "run"]
