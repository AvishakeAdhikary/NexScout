"""ReAct loop driving the apply browser (§13.2 / §13.4).

The loop:

1. Builds the §13.4 system prompt via :func:`apply.prompt.build_prompt`.
2. Sends the conversation to the LLM router (task ``apply``).
3. Parses the model's reply: either a JSON ``tool_call`` block or a bare
   ``RESULT:`` line.
4. Dispatches the tool through :func:`apply.tools.dispatch_tool`.
5. Records each step into ``transcript.jsonl`` and screenshots to
   ``screenshots/NNN_<name>.png``.
6. Halts on ``done`` (or hard cap of 50 iterations).

The LLM is expected to emit JSON like::

    {"tool": "navigate", "args": {"url": "https://…"}}

…optionally followed by a ``RESULT:`` line. The parser is lenient — fenced
code blocks and surrounding prose are tolerated.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..discovery.smartextract import extract_json
from ..llm.providers.base import Message
from .prompt import build_prompt
from .result_codes import (
    FAIL_NO_RESULT_LINE,
    FAIL_STUCK,
    parse_result_line,
)
from .tools import append_transcript, dispatch_tool, get_tool_specs

if TYPE_CHECKING:
    from ..captcha.base import CaptchaSolver
    from ..core.profile import Profile
    from ..llm.router import LLMRouter
    from .dashboard import LiveDashboard

log = logging.getLogger(__name__)

#: Hard ceiling on tool calls per job (safety cap §13.2).
MAX_ITERATIONS = 50

#: ``RESULT:`` line extractor — case-sensitive per §13.3 template.
_RESULT_RE = re.compile(r"RESULT:[A-Z_:][\w_:\- ]*", re.MULTILINE)

#: ``tool_call`` extractor — JSON object containing a ``tool`` key.
_TOOL_RE = re.compile(r"\{[^{}]*\"tool\"\s*:\s*\"[^\"]+\"[^{}]*\}", re.DOTALL)


def _read_text(path: str | Path | None) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _read_pdf_sibling(text_path: str | Path | None) -> str | None:
    """Return the .pdf sibling next to a .txt artefact, if it exists."""
    if not text_path:
        return None
    p = Path(text_path)
    pdf = p.with_suffix(".pdf")
    return str(pdf) if pdf.exists() else None


# ---------------------------------------------------------------------------
# LLM reply parsing
# ---------------------------------------------------------------------------


def parse_llm_reply(raw: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(tool_call, result_line)`` extracted from the LLM's reply.

    ``tool_call`` is a dict like ``{"tool": "navigate", "args": {…}}`` or
    ``None`` if no parseable JSON was found. ``result_line`` is the verbatim
    ``RESULT:…`` line if the model declared termination, else ``None``.
    """
    text = raw or ""

    # 1. Look for an explicit RESULT line (highest priority).
    result_match = _RESULT_RE.search(text)
    result_line = result_match.group(0) if result_match else None

    # 2. Try to extract a tool_call JSON object.
    tool_call: dict[str, Any] | None = None
    # First attempt: full ``extract_json`` over the whole reply.
    data = extract_json(text)
    if isinstance(data, dict) and "tool" in data:
        tool_call = data
    else:
        # Second attempt: scan for the smallest object containing "tool":.
        for m in _TOOL_RE.finditer(text):
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "tool" in obj:
                tool_call = obj
                break

    return tool_call, result_line


# ---------------------------------------------------------------------------
# ReAct loop
# ---------------------------------------------------------------------------


def run_agent(
    *,
    job: dict[str, Any],
    profile: Profile,
    bundle_dir: Path,
    driver: Any,
    solver: CaptchaSolver | None,
    router: LLMRouter,
    dry_run: bool = False,
    dashboard: LiveDashboard | None = None,
    worker_id: int = 0,
    max_iterations: int = MAX_ITERATIONS,
) -> tuple[str, str | None, float, bool]:
    """Drive the apply loop. Returns ``(code, reason, cost_usd, captcha_solved)``.

    ``code`` is the bare result code without the ``RESULT:`` prefix
    (``"APPLIED"``, ``"FAILED"`` etc). ``reason`` is the optional sub-reason
    (e.g. ``"sso_required"``). ``cost_usd`` is a best-effort token cost
    accumulator. ``captcha_solved`` is ``True`` if ``solve_captcha`` ever
    succeeded.
    """
    tailored_resume = _read_text(job.get("tailored_resume_path"))
    cover_letter = _read_text(job.get("cover_letter_path")) or None

    system_prompt = build_prompt(
        job=job,
        tailored_resume=tailored_resume,
        cover_letter=cover_letter,
        dry_run=dry_run,
        profile=profile,
        bundle_dir=str(bundle_dir),
    )

    tool_specs = get_tool_specs()
    user_kickoff = _kickoff_message(job)
    messages: list[Message] = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_kickoff),
    ]

    captcha_solved = False
    cost_usd = 0.0
    screenshot_idx = 0
    code = "FAILED"
    reason: str | None = FAIL_NO_RESULT_LINE

    for step in range(1, max_iterations + 1):
        try:
            reply = router.ask("apply", messages, temperature=0.1, max_tokens=2048)
        except Exception as e:
            append_transcript(bundle_dir, {"step": step, "kind": "llm_error", "error": str(e)})
            code, reason = "FAILED", "page_error"
            break

        append_transcript(bundle_dir, {"step": step, "kind": "llm", "reply": reply})
        messages.append(Message(role="assistant", content=reply))

        tool_call, result_line = parse_llm_reply(reply)

        # If the model emitted a RESULT line, stop now.
        if result_line:
            code, reason = parse_result_line(result_line)
            append_transcript(bundle_dir, {"step": step, "kind": "terminal", "code": code, "reason": reason})
            break

        if tool_call is None:
            messages.append(
                Message(
                    role="user",
                    content=(
                        "Reply could not be parsed. Emit either a JSON object "
                        '{"tool":"…","args":{…}} or a RESULT:<CODE>[:reason] '
                        f"line. Tools available: {', '.join(spec['name'] for spec in tool_specs)}."
                    ),
                )
            )
            continue

        name = str(tool_call.get("tool") or "").strip()
        args = tool_call.get("args") or {}
        if dashboard is not None:
            dashboard.tick_action(worker_id, name)

        if name == "screenshot":
            screenshot_idx += 1
        outcome = dispatch_tool(
            name,
            args,
            driver=driver,
            bundle_dir=bundle_dir,
            solver=solver,
            screenshot_idx=screenshot_idx,
        )
        append_transcript(
            bundle_dir,
            {"step": step, "kind": "tool", "tool": name, "args": args, "result": outcome.to_jsonable()},
        )

        if name == "solve_captcha" and outcome.ok and outcome.data and outcome.data.get("injected"):
            captcha_solved = True

        if name == "done" and outcome.ok and outcome.data:
            code = str(outcome.data.get("code") or "FAILED")
            reason = outcome.data.get("reason")
            break

        # Feed the tool output back to the LLM.
        messages.append(
            Message(
                role="user",
                content=json.dumps(
                    {"tool": name, "ok": outcome.ok, "data": outcome.to_jsonable().get("data"), "error": outcome.error},
                    default=str,
                ),
            )
        )

    else:  # for/else — exhausted iterations without break
        code, reason = "FAILED", FAIL_STUCK
        append_transcript(bundle_dir, {"kind": "terminal", "code": code, "reason": reason, "exhausted": True})

    return code, reason, cost_usd, captcha_solved


def _kickoff_message(job: dict[str, Any]) -> str:
    """Initial user turn — minimal directive that nudges the loop to start."""
    title = job.get("title") or "this role"
    url = job.get("application_url") or job.get("url") or ""
    return (
        f"Begin the application for: {title}\n"
        f"URL: {url}\n\n"
        "Follow the STEP-BY-STEP plan above. Emit ONE JSON tool_call per turn "
        "of the form {\"tool\":\"navigate\",\"args\":{\"url\":\"…\"}}. When the "
        "application is submitted (or terminally failed), emit a "
        "RESULT:<CODE>[:reason] line."
    )


def transcript_lines(bundle_dir: Path) -> Iterable[dict[str, Any]]:
    """Yield every JSON line from ``transcript.jsonl`` (for the web UI)."""
    p = bundle_dir / "transcript.jsonl"
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            out.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue
    return out


__all__ = [
    "MAX_ITERATIONS",
    "parse_llm_reply",
    "run_agent",
    "transcript_lines",
]
