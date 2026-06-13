"""NexScout MCP server — exposes the pipeline as agent-callable tools.

This is the headline integration that lets the OpenClaw AI agent *autonomously*
use NexScout. When a user tells OpenClaw "apply at jobs, get my resume from
NexScout", the agent now has concrete tools (``get_resume_text``,
``apply_to_job``, ``discover_jobs``, …) instead of replying that it has no
access.

Transport
---------
NexScout (Python) runs in the ``nexscout`` container; OpenClaw (Node) runs in
the ``nexscout-openclaw`` container. OpenClaw therefore cannot spawn this server
as a stdio child — it must reach it over the network. We serve **Streamable
HTTP** (the modern MCP remote transport) bound to ``0.0.0.0`` on a configurable
port (default ``8770``), reachable from OpenClaw at
``http://nexscout-mcp:8770/mcp`` on the shared ``nexscout-net`` network.

Run it with either::

    python -m nexscout.mcp.server
    nexscout-mcp            # console_scripts entry point

State directory is read from ``NEXSCOUT_DIR`` (same as the rest of NexScout).

Robustness
----------
Every tool catches its own exceptions and returns a clear, structured message
rather than raising — a single failing tool call must never crash the
long-lived server. Heavy stages (discovery, scoring, tailoring, applying) are
imported lazily inside each tool so the server starts even on a host that is
missing optional deps (a browser, an LLM backend, …); a missing dependency
surfaces as a tool-level error string, not an import-time crash.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

#: Default port the Streamable-HTTP server binds. Overridable via
#: ``NEXSCOUT_MCP_PORT``. Chosen to avoid the web UI (8765) and OpenClaw
#: (18789/18790).
DEFAULT_PORT = 8770

#: Path the Streamable-HTTP transport mounts under. OpenClaw's ``mcpServers``
#: ``url`` must point at ``http://<host>:<port>/mcp``.
MCP_PATH = "/mcp"


# ---------------------------------------------------------------------------
# Shared helpers — keep heavy NexScout imports lazy and failures contained.
# ---------------------------------------------------------------------------


def _err(action: str, exc: Exception) -> dict[str, Any]:
    """Uniform error envelope returned by every tool on failure."""
    log.warning("nexscout-mcp tool %s failed: %s", action, exc)
    return {"ok": False, "action": action, "error": f"{type(exc).__name__}: {exc}"}


def _load_profile() -> Any:
    """Load the candidate profile from ``NEXSCOUT_DIR`` (raises ConfigError)."""
    from ..core.profile import Profile

    return Profile.from_path()


def _open_db() -> Any:
    """Open / initialise the SQLite pipeline database."""
    from ..core.config import database_path
    from ..core.database import init_db

    return init_db(database_path())


def _router(profile: Any) -> Any:
    """Build an LLM router bound to the profile's budget."""
    from ..llm.budget import BudgetLedger
    from ..llm.router import LLMRouter

    return LLMRouter(
        profile,
        budget=BudgetLedger(
            monthly_usd=profile.llm.budgets.monthly_usd,
            daily_calls=profile.llm.budgets.daily_calls,
        ),
    )


# ---------------------------------------------------------------------------
# Server + tool registration
# ---------------------------------------------------------------------------


def build_server() -> Any:
    """Construct the :class:`FastMCP` server with every NexScout tool attached.

    Factory (not a module global) so tests can build an isolated instance and
    so import of this module never starts a network listener.
    """
    from mcp.server.fastmcp import FastMCP

    host = os.environ.get("NEXSCOUT_MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("NEXSCOUT_MCP_PORT", str(DEFAULT_PORT)))

    mcp = FastMCP(
        "nexscout",
        instructions=(
            "NexScout is the user's autonomous job-application agent. Use these tools to read "
            "the user's résumé/profile, inspect the application pipeline, discover/score/tailor "
            "jobs, apply to a specific job posting URL, and answer the clarifying questions "
            "NexScout raises while applying. When the user asks you to 'get my resume from "
            "NexScout' or 'apply to jobs', call these tools rather than declining."
        ),
        host=host,
        port=port,
        # Stateless + JSON responses are the recommended settings for a remote,
        # horizontally-restartable Streamable-HTTP deployment behind OpenClaw.
        stateless_http=True,
        json_response=True,
    )

    _register_tools(mcp)
    return mcp


def _register_tools(mcp: Any) -> None:
    """Attach every NexScout tool to ``mcp``. Split out for testability."""

    @mcp.tool()
    def get_profile() -> dict[str, Any]:
        """Return a structured summary of the candidate's NexScout profile/résumé.

        Includes name, contact, current/target titles, years of experience, top
        skills, and headline facts. Call this to learn who the candidate is
        before applying or answering questions on their behalf.
        """
        try:
            p = _load_profile()
            return {
                "ok": True,
                "name": p.me.legal,
                "preferred_name": p.me.pref,
                "email": p.me.email,
                "phone": p.me.phone,
                "location": ", ".join(filter(None, [p.me.city, p.me.region, p.me.country])),
                "links": p.me.links.model_dump(),
                "current_title": p.exp.current_title,
                "target_titles": p.exp.target_titles,
                "years_experience": p.exp.years,
                "education": f"{p.facts.school} {p.exp.edu}".strip(),
                "skills": p.skills.all_skills(),
                "companies": p.facts.companies,
                "projects": p.facts.projects,
                "work_authorized": p.auth.authorized,
                "needs_sponsorship": p.auth.sponsor,
            }
        except Exception as e:
            return _err("get_profile", e)

    @mcp.tool()
    def get_resume_text() -> dict[str, Any]:
        """Return the candidate's résumé as plain text.

        This is the canonical résumé NexScout tailors for each application. Use
        it whenever the user asks you to 'get my resume from NexScout' or you
        need the résumé body to attach, paste, or summarise.
        """
        try:
            p = _load_profile()
            return {"ok": True, "resume_text": p.to_resume_text()}
        except Exception as e:
            return _err("get_resume_text", e)

    @mcp.tool()
    def pipeline_status() -> dict[str, Any]:
        """Return counts describing the current state of the application pipeline.

        Keys include ``total`` (jobs discovered), ``scored``, ``tailored``,
        ``applied``, ``ready_to_apply`` and ``apply_errors``. Use this to report
        progress or decide which stage to run next.
        """
        try:
            from ..core.database import get_stats

            conn = _open_db()
            stats = get_stats(conn)
            return {"ok": True, "stats": stats}
        except Exception as e:
            return _err("pipeline_status", e)

    @mcp.tool()
    def stage_status() -> dict[str, Any]:
        """Live per-stage pipeline status + control state + per-stage backlog.

        Returns what's running right now, how far each stage has progressed,
        which stages are paused/disabled, and how many jobs are waiting at each
        stage. Use this to report exactly what NexScout is doing this moment.
        """
        try:
            from ..core import pipeline_status as ps

            profile = _load_profile()
            conn = _open_db()
            return {
                "ok": True,
                "status": ps.read_status(),
                "control": ps.read_control(),
                "backlog": ps.backlog_counts(
                    conn, min_score=profile.search.min_score, always_cover=profile.apply.always_cover_letter
                ),
            }
        except Exception as e:
            return _err("stage_status", e)

    @mcp.tool()
    def pause_automation(paused: bool = True) -> dict[str, Any]:
        """Pause or resume the autopilot. While paused it runs no new passes."""
        try:
            from ..core import pipeline_status as ps

            ps.set_paused(bool(paused))
            return {"ok": True, "paused": ps.is_paused()}
        except Exception as e:
            return _err("pause_automation", e)

    @mcp.tool()
    def stop_current_run() -> dict[str, Any]:
        """Ask the pass running right now to stop after its current job."""
        try:
            from ..core import pipeline_status as ps

            ps.request_stop()
            return {"ok": True, "stopping": True}
        except Exception as e:
            return _err("stop_current_run", e)

    @mcp.tool()
    def set_stage_enabled(stage: str, enabled: bool) -> dict[str, Any]:
        """Turn one pipeline stage on/off. Disabled stages are skipped every pass."""
        try:
            from ..core import pipeline_status as ps

            if stage not in ps.ALL_STEPS:
                return {"ok": False, "error": f"unknown stage: {stage}"}
            ps.set_stage_enabled(stage, bool(enabled))
            return {
                "ok": True,
                "stage": stage,
                "enabled": ps.stage_enabled(stage),
                "disabled_stages": ps.read_control()["disabled_stages"],
            }
        except Exception as e:
            return _err("set_stage_enabled", e)

    @mcp.tool()
    def run_stage(stage: str) -> dict[str, Any]:
        """Run a single pipeline stage once and return its summary.

        ``stage`` is one of discover/enrich/score/tailor/cover/render/apply. This
        mirrors the dashboard's per-stage control — it runs only that stage
        through the same engine (publishing live status), honouring the
        stage-lock (each stage only touches jobs the previous one finished).
        """
        try:
            from ..core import pipeline_status as ps
            from ..openclaw.tick import run as tick_run

            if stage not in ps.ALL_STEPS:
                return {"ok": False, "error": f"unknown stage: {stage}"}
            profile = _load_profile()
            summary = tick_run(profile=profile, stages=[stage], source="mcp")
            return {"ok": True, "stage": stage, "summary": summary}
        except Exception as e:
            return _err("run_stage", e)

    @mcp.tool()
    def discover_jobs(limit_per_engine: int = 10) -> dict[str, Any]:
        """Run job discovery across the configured search engines/boards.

        Pulls up to ``limit_per_engine`` new postings per engine into the
        pipeline (duplicates are skipped). Returns the number of new jobs found.
        """
        try:
            from ..pipeline import run_discover_stage

            profile = _load_profile()
            conn = _open_db()
            router = None
            try:
                router = _router(profile)
            except Exception as e:  # discovery still works without smartextract
                log.info("discover_jobs: running without LLM router (%s)", e)
            new = run_discover_stage(
                conn=conn,
                profile=profile,
                router=router,
                limit_per_engine=max(0, int(limit_per_engine)),
            )
            return {"ok": True, "new_jobs": int(new)}
        except Exception as e:
            return _err("discover_jobs", e)

    @mcp.tool()
    def score_jobs(limit: int = 50) -> dict[str, Any]:
        """Score up to ``limit`` enriched-but-unscored jobs for fit (0-10).

        Uses the candidate's profile + the LLM router. Returns how many jobs
        were scored. Run after ``discover_jobs`` and before ``tailor_jobs``.
        """
        try:
            from ..pipeline import run_score_stage

            profile = _load_profile()
            conn = _open_db()
            router = _router(profile)
            n = run_score_stage(conn=conn, router=router, profile=profile, limit=max(0, int(limit)))
            return {"ok": True, "scored": int(n)}
        except Exception as e:
            return _err("score_jobs", e)

    @mcp.tool()
    def tailor_jobs(limit: int = 5) -> dict[str, Any]:
        """Tailor the résumé for up to ``limit`` high-fit jobs.

        Only jobs scoring at/above the configured ``min_score`` are tailored.
        Returns how many résumés were produced. Run after ``score_jobs``; a
        tailored résumé is required before a job becomes eligible to apply.
        """
        try:
            from ..pipeline import run_tailor_stage

            profile = _load_profile()
            conn = _open_db()
            router = _router(profile)
            n = run_tailor_stage(conn=conn, router=router, profile=profile, limit=max(0, int(limit)))
            return {"ok": True, "tailored": int(n)}
        except Exception as e:
            return _err("tailor_jobs", e)

    @mcp.tool()
    def apply_to_job(url: str) -> dict[str, Any]:
        """Apply to a single job posting by URL (one-shot).

        Mirrors ``nexscout apply --url <url>``: resets the job's apply state and
        runs one apply attempt with a single headless browser worker. The job
        must already be discovered+tailored in the pipeline for the agent to
        have a résumé to submit. Returns whether an attempt ran and the new
        apply status/error recorded for that URL.
        """
        try:
            url = (url or "").strip()
            if not url:
                return {"ok": False, "action": "apply_to_job", "error": "empty url"}

            profile = _load_profile()
            conn = _open_db()

            # Mirror the CLI one-shot path: clear prior state for this URL so the
            # atomic acquire query will pick it up.
            conn.execute(
                "UPDATE jobs SET apply_status=NULL, apply_attempts=0 WHERE url=?",
                (url,),
            )

            from ..agent_backends import get_backend
            from ..apply.orchestrator import worker_loop
            from ..browser.pool import BrowserPool
            from ..captcha.capsolver import CapSolverSolver

            backend_name = profile.apply.backend or "native"
            try:
                runner = get_backend(backend_name)
            except Exception as e:
                log.warning("apply_to_job: backend %r unavailable (%s); using native", backend_name, e)
                backend_name, runner = "native", None

            solver = CapSolverSolver(api_key=profile.captcha.api_key) if profile.captcha.api_key else None
            router = _router(profile)
            pool = BrowserPool(workers=1, headless=True)
            try:
                processed = worker_loop(
                    0,
                    profile,
                    conn,
                    solver,
                    router,
                    pool=pool,
                    runner=runner,
                    backend=backend_name,
                    limit=1,
                    dry_run=profile.apply.dry_run,
                    continuous=False,
                )
            finally:
                from contextlib import suppress

                with suppress(Exception):
                    pool.close_all()

            row = conn.execute("SELECT apply_status, apply_error FROM jobs WHERE url=?", (url,)).fetchone()
            return {
                "ok": True,
                "url": url,
                "attempts_run": int(processed),
                "apply_status": (row["apply_status"] if row else None),
                "apply_error": (row["apply_error"] if row else None),
                "note": (
                    "No attempt ran — the URL is not in the pipeline or has no tailored résumé yet. "
                    "Run discover_jobs/score_jobs/tailor_jobs first."
                    if not processed
                    else "Apply attempt completed; see apply_status."
                ),
            }
        except Exception as e:
            return _err("apply_to_job", e)

    @mcp.tool()
    def list_open_questions() -> dict[str, Any]:
        """List the unanswered clarifying questions NexScout raised while applying.

        NexScout pauses an application and records a question when it needs human
        input (e.g. an unusual application field, a manual-CAPTCHA gate). Each
        item has an ``id``, ``question`` text and optional ``job_url``. Answer
        them with ``answer_question`` to unblock those applications.
        """
        try:
            conn = _open_db()
            rows = conn.execute(
                "SELECT id, job_url, question, asked_at FROM pending_questions " "WHERE answered_at IS NULL ORDER BY id"
            ).fetchall()
            return {"ok": True, "questions": [dict(r) for r in rows]}
        except Exception as e:
            return _err("list_open_questions", e)

    @mcp.tool()
    def answer_question(question_id: int, answer: str) -> dict[str, Any]:
        """Answer an open clarifying question by its ``id``.

        Records the answer, persists it to NexScout's learned-answers memory for
        reuse on future applications, and (when the question paused a specific
        job) clears that job's hold so it becomes eligible to apply again.
        """
        try:
            from datetime import UTC, datetime

            from ..openclaw.memory import append_learned_answer

            conn = _open_db()
            qid = int(question_id)
            reply = (answer or "").strip()
            if not reply:
                return {"ok": False, "action": "answer_question", "error": "empty answer"}

            row = conn.execute(
                "SELECT id, job_url, question FROM pending_questions WHERE id=? AND answered_at IS NULL",
                (qid,),
            ).fetchone()
            if row is None:
                return {"ok": False, "action": "answer_question", "error": f"no open question #{qid}"}

            now = datetime.now(UTC).isoformat()
            conn.execute(
                "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
                (reply, now, qid),
            )
            if row["job_url"]:
                conn.execute(
                    "UPDATE jobs SET apply_status=NULL WHERE url=? AND apply_status='paused_for_question'",
                    (row["job_url"],),
                )
            from contextlib import suppress

            with suppress(Exception):
                append_learned_answer(row["question"], reply, ts=now, source="openclaw-mcp")
            return {"ok": True, "answered_id": qid}
        except Exception as e:
            return _err("answer_question", e)

    @mcp.tool()
    def run_once(wall_clock_s: float = 300.0) -> dict[str, Any]:
        """Run one bounded end-to-end pipeline pass and return the summary.

        Executes discover → enrich → score → tailor → render → apply →
        surface-questions, each capped by NexScout's per-stage budgets and an
        overall soft ``wall_clock_s`` deadline. This is the autonomous
        'do a chunk of work now' tool. Returns per-stage counts.
        """
        try:
            from ..openclaw.tick import run as tick_run

            profile = _load_profile()
            summary = tick_run(profile=profile, wall_clock_s=float(wall_clock_s))
            return {"ok": True, "summary": summary}
        except Exception as e:
            return _err("run_once", e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Console-script / ``python -m`` entry point.

    Binds the Streamable-HTTP transport on ``NEXSCOUT_MCP_HOST``/
    ``NEXSCOUT_MCP_PORT`` (default ``0.0.0.0:8770``) under :data:`MCP_PATH`.
    """
    logging.basicConfig(
        level=os.environ.get("NEXSCOUT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from ..core.logsetup import setup_file_logging

    setup_file_logging("mcp")
    server = build_server()
    log.info(
        "starting nexscout-mcp (streamable-http) on %s:%s%s",
        getattr(server.settings, "host", "0.0.0.0"),
        getattr(server.settings, "port", DEFAULT_PORT),
        MCP_PATH,
    )
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
