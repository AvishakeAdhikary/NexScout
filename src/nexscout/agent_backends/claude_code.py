"""Optional ``claude`` CLI shim.

If the user has Claude Code installed (``claude`` on PATH), we shell out to it
with a single-turn ``--message`` invocation. Otherwise the function raises
:class:`ConfigError`. The shim is intentionally minimal — it lives here so
``nexscout apply --backend claude_code`` doesn't ``ImportError``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..apply.prompt import build_prompt
from ..apply.result_codes import FAIL_NO_RESULT_LINE, parse_result_line
from ..core.errors import ConfigError

log = logging.getLogger(__name__)


def _claude_path() -> str | None:
    return shutil.which("claude")


def run(
    *,
    job: dict[str, Any],
    profile: Any,
    bundle_dir: Path,
    driver: Any,
    solver: Any,
    router: Any,
    dry_run: bool = False,
    dashboard: Any = None,
    worker_id: int = 0,
    max_iterations: int = 50,
) -> tuple[str, str | None, float, bool]:
    """Shell out to ``claude`` (if installed). Otherwise raise ConfigError."""
    _ = (driver, solver, router, dashboard, worker_id, max_iterations)
    binary = _claude_path()
    if binary is None:
        raise ConfigError("claude_code backend requires the `claude` CLI on PATH; use --backend native instead.")

    tailored = ""
    cover_letter: str | None = None
    if job.get("tailored_resume_path"):
        p = Path(str(job["tailored_resume_path"]))
        if p.exists():
            tailored = p.read_text(encoding="utf-8")
    if job.get("cover_letter_path"):
        p = Path(str(job["cover_letter_path"]))
        if p.exists():
            cover_letter = p.read_text(encoding="utf-8")

    system_prompt = build_prompt(
        job=job,
        tailored_resume=tailored,
        cover_letter=cover_letter,
        dry_run=dry_run,
        profile=profile,
        bundle_dir=str(bundle_dir),
    )
    user_msg = f"Apply to: {job.get('title') or ''}\nURL: {job.get('application_url') or job.get('url')}"

    try:
        proc = subprocess.run(
            [binary, "--print", system_prompt + "\n\n" + user_msg],
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        return "FAILED", f"claude_cli_error: {e}", 0.0, False

    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # Look for a RESULT: line in the output.
    for line in reversed(out.splitlines()):
        if line.strip().startswith("RESULT:"):
            code, reason = parse_result_line(line.strip())
            return code, reason, 0.0, False
    return "FAILED", FAIL_NO_RESULT_LINE, 0.0, False


__all__ = ["run"]
