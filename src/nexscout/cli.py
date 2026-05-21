"""Typer-based CLI for NexScout.

Implements (so far): ``init``, ``doctor``, and a top-level ``--version`` flag.
Other commands (``run``, ``apply``, ``web``, ``status``, ``tick``…) land in
later milestones.
"""

from __future__ import annotations

import shutil
import sys
from typing import Annotated

import typer
from rich.table import Table

from . import __version__
from .core.config import get_chrome_path, nexscout_dir, profile_path
from .core.errors import ConfigError
from .core.logging import console, setup_logging
from .core.profile import Profile

app = typer.Typer(
    add_completion=False,
    help="NexScout — always-on autonomous job-application agent.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"nexscout {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Print version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Verbose logging.")] = False,
) -> None:
    setup_logging("DEBUG" if verbose else "INFO")


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@app.command()
def init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing profile.")] = False,
) -> None:
    """Run the interactive wizard to create ``~/.nexscout/profile.yaml``."""
    from .wizard import run_wizard  # local import keeps `--version` fast

    run_wizard(force=force)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _has_latex_engine() -> str | None:
    for name in ("tectonic", "latexmk", "pdflatex"):
        if shutil.which(name):
            return name
    return None


def _detect_tier(profile: Profile | None, chrome: str | None, latex: str | None) -> str:
    """Compute the NexScout readiness tier.

    * **T0** — Chrome missing.
    * **T1** — Chrome only, no LLM.
    * **T2** — LLM provider configured (discovery + scoring + tailor work).
    * **T3** — T2 + a LaTeX engine on PATH (apply ready). CAPTCHA is **not**
      required for T3: sites with CAPTCHAs are parked for manual review when
      no provider is configured (Task-4 spec).
    """
    if not chrome:
        return "T0"
    has_llm = bool(profile and (profile.llm.primary or profile.llm.fallback))
    if not has_llm:
        return "T1"
    if latex:
        return "T3"
    return "T2"


@app.command()
def doctor(
    quiet: Annotated[
        bool,
        typer.Option("--quiet", help="Suppress table output; exit 0 only when T2+ is ready."),
    ] = False,
) -> None:
    """Diagnostic check.

    Without ``--quiet``: prints a table and exits non-zero on any hard failure.
    With ``--quiet``: prints nothing and exits 0 only when the prereqs are
    healthy enough to declare T2 (used by Docker healthcheck).
    """
    c = console()
    table = Table(title="NexScout doctor", show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    issues: list[str] = []

    py_ok = sys.version_info >= (3, 11)
    table.add_row("Python >=3.11", "OK" if py_ok else "FAIL", sys.version.split()[0])
    if not py_ok:
        issues.append("python<3.11")

    nx_dir = nexscout_dir()
    writable = nx_dir.exists() and nx_dir.is_dir()
    if not writable:
        try:
            nx_dir.mkdir(parents=True, exist_ok=True)
            writable = True
        except OSError:
            writable = False
    table.add_row("NexScout dir", "OK" if writable else "FAIL", str(nx_dir))
    if not writable:
        issues.append("nexscout_dir_not_writable")

    chrome = get_chrome_path()
    table.add_row("Chrome/Chromium", "OK" if chrome else "MISSING", chrome or "not found")
    if not chrome:
        issues.append("chrome_missing")

    latex = _has_latex_engine()
    table.add_row("LaTeX engine", "OK" if latex else "MISSING", latex or "no tectonic/latexmk/pdflatex")

    profile: Profile | None = None
    profile_p = profile_path()
    if not profile_p.exists():
        table.add_row("profile.yaml", "MISSING", "run `nexscout init`")
        issues.append("profile_missing")
    else:
        try:
            profile = Profile.from_path(profile_p)
            table.add_row("profile.yaml", "OK", str(profile_p))
        except ConfigError as e:
            table.add_row("profile.yaml", "INVALID", str(e))
            issues.append("profile_invalid")

    if profile is not None:
        table.add_row(
            "LLM provider",
            "OK" if (profile.llm.primary or profile.llm.fallback) else "FAIL",
            f"primary={profile.llm.primary}, fallback={profile.llm.fallback}",
        )
        if not profile.captcha.api_key:
            table.add_row(
                "CAPTCHA api_key",
                "WARN",
                "no CAPTCHA provider configured; sites requiring CAPTCHA solving "
                "will be parked for manual user review.",
            )
        else:
            table.add_row("CAPTCHA api_key", "OK", profile.captcha.provider)

    tier = _detect_tier(profile, chrome, latex)
    tier_blurbs = {
        "T0": "below T1",
        "T1": "discovery only",
        "T2": "LLM ready",
        "T3": "apply ready",
    }
    table.add_row("Tier", tier, tier_blurbs[tier])

    if quiet:
        # Healthcheck mode — succeed only when prereqs reach T2.
        healthy = not issues and tier in {"T2", "T3"}
        raise typer.Exit(code=0 if healthy else 1)

    c.print(table)
    if issues:
        c.print(f"[red]Issues: {', '.join(issues)}[/red]")
        raise typer.Exit(code=1)
    c.print("[green]All green.[/green]")


# ---------------------------------------------------------------------------
# run / apply — early CAPTCHA gate (full pipeline lands in M7+)
# ---------------------------------------------------------------------------


def _load_profile_with_captcha_warning(stage: str) -> Profile:
    """Load the profile and warn (do not refuse) when ``captcha.api_key`` is unset.

    CAPTCHA is now OPTIONAL (Task-4 spec). Sites requiring CAPTCHA solving when
    no provider is configured are marked for manual review via the
    ``RESULT:CAPTCHA_MANUAL`` result code; a pending_question row is created so
    the web UI / OpenClaw channel surfaces it to the user.
    """
    profile_p = profile_path()
    if not profile_p.exists():
        raise ConfigError(f"profile not found at {profile_p}; run `nexscout init` first")
    profile = Profile.from_path(profile_p)
    if not profile.captcha.api_key:
        console().print(
            f"[yellow]warning:[/yellow] no CAPTCHA provider configured for `nexscout {stage}` — "
            "sites with CAPTCHAs will be marked for manual review."
        )
    return profile


@app.command()
def run(
    stages: Annotated[
        list[str] | None,
        typer.Argument(help="Stages: discover|enrich|score|tailor|cover|render|all"),
    ] = None,
) -> None:
    """Run pipeline stages. Refuses to start without a CAPTCHA api_key."""
    c = console()
    try:
        profile = _load_profile_with_captcha_warning("run")
    except ConfigError as e:
        c.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    requested = list(stages or ())
    c.print(f"[green]NexScout run starting[/green] (profile={profile.me.legal!r}, stages={requested or 'all'})")
    # Full pipeline orchestration lives in pipeline.py and lands fully in M11
    # (streaming). For M6 we only enforce the gate and exit cleanly.


@app.command(context_settings={"allow_extra_args": False})
def apply(
    workers: Annotated[int, typer.Option("--workers", help="Worker count.")] = 1,
    headless: Annotated[bool, typer.Option("--headless/--headed", help="Run Chrome headless.")] = True,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Don't actually click Submit.")] = False,
    continuous: Annotated[bool, typer.Option("--continuous", help="Poll for new jobs forever.")] = False,
    url: Annotated[str | None, typer.Option("--url", help="One-shot apply to this URL.")] = None,
    backend: Annotated[str, typer.Option("--backend", help="native | claude_code | openai_assistant")] = "native",
    limit: Annotated[int, typer.Option("--limit", help="Stop after N jobs (0 = unlimited).")] = 0,
) -> None:
    """Submit applications. Refuses to start without a CAPTCHA api_key."""
    from .agent_backends import get_backend
    from .apply.dashboard import LiveDashboard
    from .apply.orchestrator import worker_loop
    from .browser.pool import BrowserPool
    from .captcha.capsolver import CapSolverSolver
    from .core.database import init_db
    from .llm.budget import BudgetLedger
    from .llm.router import LLMRouter

    c = console()
    try:
        profile = _load_profile_with_captcha_warning("apply")
    except ConfigError as e:
        c.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    if backend not in {"native", "claude_code", "openai_assistant"}:
        c.print(f"[red]unknown backend: {backend}[/red]")
        raise typer.Exit(code=1)

    runner = get_backend(backend)
    solver = CapSolverSolver(api_key=profile.captcha.api_key) if profile.captcha.api_key else None
    budget = BudgetLedger(
        monthly_usd=profile.llm.budgets.monthly_usd,
        daily_calls=profile.llm.budgets.daily_calls,
    )
    router = LLMRouter(profile, budget=budget)
    conn = init_db()

    if url:
        # Tag a single job for this URL so the acquire query picks it up.
        conn.execute(
            "UPDATE jobs SET apply_status=NULL, apply_attempts=0 WHERE url=?",
            (url,),
        )

    pool = BrowserPool(workers=workers, headless=headless)
    c.print(f"[green]NexScout apply starting[/green] backend={backend} workers={workers}")

    try:
        with LiveDashboard(workers=workers, console=c) as dashboard:
            total = 0
            for w in range(workers):
                total += worker_loop(
                    w,
                    profile,
                    conn,
                    solver,
                    router,
                    pool=pool,
                    runner=runner,
                    dashboard=dashboard,
                    limit=limit,
                    dry_run=dry_run,
                    backend=backend,
                    continuous=continuous,
                )
            c.print(f"[green]Done.[/green] Processed {total} jobs.")
    finally:
        pool.close_all()


# ---------------------------------------------------------------------------
# tick / question / status / web — M8/M9 wiring
# ---------------------------------------------------------------------------


@app.command()
def tick(
    wall_clock_s: Annotated[float, typer.Option("--wall-clock", help="Soft time cap (s).")] = 300.0,
) -> None:
    """Run a single OpenClaw heartbeat tick (bounded unit of work)."""
    from .openclaw.tick import run as tick_run

    profile_p = profile_path()
    if not profile_p.exists():
        console().print(f"[red]profile not found at {profile_p}[/red]")
        raise typer.Exit(code=1)
    profile = Profile.from_path(profile_p)
    summary = tick_run(profile=profile, wall_clock_s=wall_clock_s)
    typer.echo(f"summary: {summary}")


question_app = typer.Typer(help="Manage pending clarifying questions.")
app.add_typer(question_app, name="question")


@question_app.command("list")
def question_list(
    fmt: Annotated[str, typer.Option("--format", help="text|json|openclaw")] = "text",
) -> None:
    """List outstanding clarifying questions."""
    import json as json_mod

    from .core.database import init_db

    conn = init_db()
    rows = conn.execute(
        "SELECT id, job_url, question, asked_at FROM pending_questions "
        "WHERE answered_at IS NULL ORDER BY id"
    ).fetchall()
    items = [dict(r) for r in rows]
    if fmt == "json":
        typer.echo(json_mod.dumps(items, indent=2))
    elif fmt == "openclaw":
        if not items:
            typer.echo("nexscout: no pending questions")
        else:
            for r in items:
                typer.echo(f"nexscout: Q{r['id']}: {r['question']}")
    elif not items:
        console().print("[dim]no pending questions[/dim]")
    else:
        for r in items:
            console().print(f"[yellow]Q{r['id']}[/yellow] {r['question']}")


@question_app.command("answer")
def question_answer(
    question: Annotated[str, typer.Option("--question", "-q", help="Verbatim question text.")],
    reply: Annotated[str, typer.Option("--reply", "-a", help="Answer text.")],
) -> None:
    """Answer a pending question (also persisted to OpenClaw memory)."""
    from .openclaw.skill import handle_answer

    out = handle_answer(question, reply)
    typer.echo(out.get("text") or "ok")


@app.command()
def status(
    fmt: Annotated[str, typer.Option("--format", help="text|json|openclaw")] = "text",
) -> None:
    """Show pipeline stats."""
    import json as json_mod

    from .core.database import get_stats, init_db

    stats = get_stats(init_db())
    if fmt == "json":
        typer.echo(json_mod.dumps(stats, indent=2))
        return
    if fmt == "openclaw":
        line = (
            f"nexscout: total={stats['total']} scored={stats['scored']} "
            f"applied={stats['applied']} ready={stats['ready_to_apply']} "
            f"errors={stats['apply_errors']}"
        )
        typer.echo(line)
        return
    c = console()
    for k, v in stats.items():
        c.print(f"{k}: {v}")


@app.command()
def web(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
    init_pw: Annotated[bool, typer.Option("--init-pw", help="Set the web password.")] = False,
) -> None:
    """Run the FastAPI web UI."""
    from .web.app import create_app
    from .web.auth import set_password

    if init_pw:
        import getpass

        pw = getpass.getpass("Web password: ")
        if not pw:
            raise typer.Exit(code=1)
        set_password(pw)
        typer.echo("Password set.")
        return

    try:
        import uvicorn
    except ImportError as e:
        raise ConfigError("uvicorn is not installed") from e
    uvicorn.run(create_app, host=host, port=port, factory=True)


controls_app = typer.Typer(help="Pause / resume / tick controls.")
app.add_typer(controls_app, name="controls")


@controls_app.command("pause")
def controls_pause() -> None:
    """Write the ~/.nexscout/paused.flag marker."""
    from datetime import UTC, datetime

    from .core.config import nexscout_dir

    flag = nexscout_dir() / "paused.flag"
    flag.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    typer.echo("paused")


@controls_app.command("resume")
def controls_resume() -> None:
    """Remove the pause marker."""
    from .core.config import nexscout_dir

    flag = nexscout_dir() / "paused.flag"
    if flag.exists():
        flag.unlink()
    typer.echo("resumed")
