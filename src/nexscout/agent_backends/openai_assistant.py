"""Optional OpenAI Assistants-API backend.

If the user supplies ``OPENAI_API_KEY`` and the ``openai`` SDK is installed,
we drive an Assistants thread. Otherwise raises :class:`ConfigError`. The
implementation is intentionally light — full feature-parity with the native
ReAct loop is out of scope for M7.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from ..apply.prompt import build_prompt
from ..apply.result_codes import FAIL_NO_RESULT_LINE, parse_result_line
from ..core.errors import ConfigError

log = logging.getLogger(__name__)


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
    """Drive an OpenAI Assistant. Falls back to ConfigError when unavailable."""
    _ = (driver, solver, router, dashboard, worker_id, max_iterations)
    if not os.environ.get("OPENAI_API_KEY"):
        raise ConfigError("openai_assistant backend requires OPENAI_API_KEY; use --backend native.")
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError as e:
        raise ConfigError("openai package is not installed") from e

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

    client = OpenAI()  # type: ignore[call-arg]
    try:
        assistant = client.beta.assistants.create(
            name="NexScout apply",
            instructions=system_prompt,
            model=os.environ.get("OPENAI_ASSISTANT_MODEL", "gpt-4o-mini"),
        )
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=f"Apply to: {job.get('title') or ''}",
        )
        run_obj = client.beta.threads.runs.create_and_poll(thread_id=thread.id, assistant_id=assistant.id)
    except Exception as e:
        return "FAILED", f"openai_assistant_error: {e}", 0.0, False

    if run_obj.status != "completed":
        return "FAILED", f"assistant_status_{run_obj.status}", 0.0, False

    messages = client.beta.threads.messages.list(thread_id=thread.id)
    text = ""
    for m in messages.data:
        for c in m.content:
            if getattr(c, "type", "") == "text":
                text += getattr(c.text, "value", "")  # type: ignore[union-attr]
    for line in reversed(text.splitlines()):
        if line.strip().startswith("RESULT:"):
            code, reason = parse_result_line(line.strip())
            return code, reason, 0.0, False
    return "FAILED", FAIL_NO_RESULT_LINE, 0.0, False


__all__ = ["run"]
