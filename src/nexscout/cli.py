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
    if not chrome:
        return "T0"
    has_llm = bool(profile and (profile.llm.primary or profile.llm.fallback))
    if not has_llm:
        return "T1"
    has_captcha = bool(profile and profile.captcha.api_key)
    if latex and has_captcha:
        return "T3"
    return "T2"


@app.command()
def doctor() -> None:
    """Diagnostic check. Non-zero exit on missing prereqs."""
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
            table.add_row("CAPTCHA api_key", "MISSING", "set CAPTCHA_API_KEY")
            issues.append("captcha_missing")
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

    c.print(table)
    if issues:
        c.print(f"[red]Issues: {', '.join(issues)}[/red]")
        raise typer.Exit(code=1)
    c.print("[green]All green.[/green]")


# ---------------------------------------------------------------------------
# run / apply — early CAPTCHA gate (full pipeline lands in M7+)
# ---------------------------------------------------------------------------


def _ensure_captcha_configured(stage: str) -> Profile:
    """Load the profile and refuse to proceed without ``captcha.api_key``."""
    profile_p = profile_path()
    if not profile_p.exists():
        raise ConfigError(f"profile not found at {profile_p}; run `nexscout init` first")
    profile = Profile.from_path(profile_p)
    if not profile.captcha.api_key:
        raise ConfigError(
            f"`nexscout {stage}` requires profile.captcha.api_key — set CAPTCHA_API_KEY and rerun"
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
        profile = _ensure_captcha_configured("run")
    except ConfigError as e:
        c.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    requested = list(stages or ())
    c.print(f"[green]NexScout run starting[/green] (profile={profile.me.legal!r}, stages={requested or 'all'})")
    # Full pipeline orchestration lives in pipeline.py and lands fully in M11
    # (streaming). For M6 we only enforce the gate and exit cleanly.


@app.command()
def apply() -> None:
    """Submit applications. Refuses to start without a CAPTCHA api_key."""
    c = console()
    try:
        profile = _ensure_captcha_configured("apply")
    except ConfigError as e:
        c.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None
    c.print(f"[green]NexScout apply ready[/green] (profile={profile.me.legal!r})")
    # The full apply orchestrator lands in M7.
