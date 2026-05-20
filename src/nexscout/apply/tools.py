"""Agent tools (§13.2 of plan.md) — 12 functions the LLM can call.

Each tool returns a :class:`ToolResult`. Tools never raise; failures surface
as ``ok=False`` with an ``error`` string. The agent loop logs each step into
``transcript.jsonl`` regardless of outcome.
"""

from __future__ import annotations

import json
import logging
import re
import smtplib
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup, Tag

from ..captcha.detect import detect_in_driver
from ..captcha.inject import inject as inject_token
from ..core.errors import CaptchaUnsolvable
from . import form_filler
from .result_codes import parse_result_line

if TYPE_CHECKING:
    from ..captcha.base import CaptchaSolver

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool result
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Outcome of a single tool invocation."""

    ok: bool
    data: Any = None
    error: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": _shrink_for_log(self.data),
            "error": self.error,
            **({"extras": self.extras} if self.extras else {}),
        }


def _shrink_for_log(value: Any) -> Any:
    """Truncate huge payloads (DOM snapshots, screenshots) for the transcript."""
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + f"... ({len(value)} chars truncated)"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {k: _shrink_for_log(v) for k, v in value.items()}
    if isinstance(value, list) and len(value) > 50:
        return [_shrink_for_log(v) for v in value[:50]] + [f"... ({len(value)} items truncated)"]
    return value


# ---------------------------------------------------------------------------
# read_page — simplified DOM snapshot
# ---------------------------------------------------------------------------

#: ``class`` attribute strings longer than this are dropped (§13.2 says
#: ``class<=30chars``).
MAX_CLASS_LEN = 30

#: Allow-listed attribute names per §13.2. ``data-*`` and ``aria-*`` are
#: handled as prefixes; everything else is matched verbatim.
ALLOW_ATTRS_LITERAL: frozenset[str] = frozenset(
    {"id", "href", "role", "type", "name", "for"}
)
ALLOW_ATTR_PREFIXES: tuple[str, ...] = ("data-", "aria-")
SPECIFIC_DATA_ALLOWLIST: frozenset[str] = frozenset(
    {"data-testid", "data-id", "data-type", "data-slug"}
)

#: Tags we always strip outright before serialising.
STRIP_TAGS: frozenset[str] = frozenset(
    {"script", "style", "noscript", "svg", "iframe", "link", "meta"}
)


def simplify_dom(html: str) -> str:
    """Return a cleaned DOM snapshot per §13.2 allow-list."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue
        new_attrs: dict[str, Any] = {}
        for attr, val in list(tag.attrs.items()):
            attr_lc = attr.lower()
            keep = False
            if attr_lc in ALLOW_ATTRS_LITERAL or attr_lc.startswith(ALLOW_ATTR_PREFIXES):
                keep = True
            elif attr_lc == "class":
                class_str = " ".join(val) if isinstance(val, list) else str(val or "")
                if class_str and len(class_str) <= MAX_CLASS_LEN:
                    new_attrs["class"] = class_str
                continue
            if keep:
                new_attrs[attr_lc] = val
        tag.attrs = new_attrs

    # Discard the <head> entirely if present.
    head = soup.find("head")
    if head is not None:
        head.decompose()

    return str(soup)


# ---------------------------------------------------------------------------
# Driver helpers (used by tools below)
# ---------------------------------------------------------------------------


def _safe(call: Any, *args: Any, **kw: Any) -> tuple[bool, Any, str | None]:
    try:
        return True, call(*args, **kw), None
    except Exception as e:
        return False, None, str(e)


def _bundle_screenshot_path(bundle_dir: Path, idx: int, name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", name or "step")
    shots = bundle_dir / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    return shots / f"{idx:03d}_{safe_name}.png"


# ---------------------------------------------------------------------------
# The 12 tools
# ---------------------------------------------------------------------------


def navigate(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``navigate(url)`` — drive to a URL."""
    url = str(args.get("url", "")).strip()
    if not url:
        return ToolResult(ok=False, error="missing url")
    ok, _, err = _safe(driver.get, url)
    return ToolResult(ok=ok, data={"url": url}, error=err)


def read_page(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``read_page()`` — return the simplified DOM snapshot."""
    _ = args
    _ = bundle_dir
    try:
        html = driver.page_source
    except Exception as e:
        return ToolResult(ok=False, error=str(e))
    cleaned = simplify_dom(html or "")
    url = ""
    with _suppress():
        url = getattr(driver, "current_url", "") or ""
    title = ""
    with _suppress():
        title = getattr(driver, "title", "") or ""
    return ToolResult(ok=True, data={"url": url, "title": title, "html": cleaned})


def screenshot(driver: Any, args: dict[str, Any], bundle_dir: Path, *, idx: int = 0) -> ToolResult:
    """``screenshot(name)`` — save a PNG to the bundle."""
    name = str(args.get("name", "step"))
    path = _bundle_screenshot_path(bundle_dir, idx, name)
    ok, _, err = _safe(driver.save_screenshot, str(path))
    if not ok:
        return ToolResult(ok=False, error=err)
    return ToolResult(ok=True, data={"path": str(path)})


def click(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``click(ref)`` — XPath/CSS/data-testid click."""
    _ = bundle_dir
    ref = str(args.get("ref", "")).strip()
    if not ref:
        return ToolResult(ok=False, error="missing ref")
    ok = form_filler.click(driver, ref)
    return ToolResult(ok=ok, data={"ref": ref}, error=None if ok else "click failed")


def fill_form(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``fill_form(fields)`` — batch-fill."""
    _ = bundle_dir
    fields = args.get("fields") or {}
    if not isinstance(fields, dict):
        return ToolResult(ok=False, error="fields must be a dict")
    outcome = form_filler.fill_form(driver, fields)
    ok = all(outcome.values()) if outcome else False
    return ToolResult(ok=ok, data=outcome, error=None if ok else "one or more fields failed")


def select(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``select(ref, value)`` — pick an option."""
    _ = bundle_dir
    ref = str(args.get("ref", "")).strip()
    value = args.get("value")
    ok = form_filler.select_option(driver, ref, str(value or ""))
    return ToolResult(ok=ok, data={"ref": ref, "value": value}, error=None if ok else "select failed")


def upload(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``upload(ref, path)`` — file chooser."""
    _ = bundle_dir
    ref = str(args.get("ref", "")).strip()
    path = str(args.get("path", "")).strip()
    if not path or not Path(path).exists():
        return ToolResult(ok=False, error=f"file does not exist: {path}")
    ok = form_filler.upload(driver, ref, path)
    return ToolResult(ok=ok, data={"ref": ref, "path": path}, error=None if ok else "upload failed")


def tabs(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``tabs(action, idx)`` — list/select browser tabs."""
    _ = bundle_dir
    action = str(args.get("action", "list"))
    if action == "list":
        try:
            handles = list(driver.window_handles or [])
            current = getattr(driver, "current_window_handle", None)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))
        return ToolResult(ok=True, data={"count": len(handles), "handles": handles, "current": current})
    if action == "select":
        idx = int(args.get("idx", 0))
        try:
            handles = list(driver.window_handles or [])
            if not 0 <= idx < len(handles):
                return ToolResult(ok=False, error=f"idx {idx} out of range 0..{len(handles) - 1}")
            driver.switch_to.window(handles[idx])
            return ToolResult(ok=True, data={"selected": handles[idx]})
        except Exception as e:
            return ToolResult(ok=False, error=str(e))
    return ToolResult(ok=False, error=f"unknown action {action!r}")


def solve_captcha(
    driver: Any,
    args: dict[str, Any],
    bundle_dir: Path,
    *,
    solver: CaptchaSolver | None = None,
) -> ToolResult:
    """``solve_captcha()`` — DETECT → solve → inject. Mandatory (§15)."""
    _ = bundle_dir
    _ = args
    if solver is None:
        return ToolResult(ok=False, error="no captcha solver wired")

    detection = detect_in_driver(driver)
    if not detection or not detection.get("type"):
        return ToolResult(ok=True, data={"detected": None})

    kind = detection.get("type")
    sitekey = detection.get("sitekey") or ""
    url = detection.get("url") or ""
    extras = {k: v for k, v in detection.items() if k not in {"type", "sitekey", "url"}}
    if not kind or kind == "turnstile_script_only":
        return ToolResult(ok=False, error=f"captcha not solvable yet: {kind}")

    try:
        token = solver.solve(kind, sitekey, url, **extras)
    except CaptchaUnsolvable as e:
        return ToolResult(ok=False, error=str(e), data={"detected": detection})
    except Exception as e:
        return ToolResult(ok=False, error=f"solver error: {e}", data={"detected": detection})

    try:
        inject_token(driver, kind, token)
    except Exception as e:
        return ToolResult(ok=False, error=f"inject error: {e}", data={"detected": detection})
    return ToolResult(ok=True, data={"detected": detection, "injected": True})


def send_email(driver: Any, args: dict[str, Any], bundle_dir: Path, *, smtp_factory: Any = None) -> ToolResult:
    """``send_email(to, subject, body, attachments)`` — fall-back for email-only postings."""
    _ = driver
    _ = bundle_dir
    to = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", "")).strip()
    attachments = list(args.get("attachments") or [])
    if not to or not subject:
        return ToolResult(ok=False, error="missing to/subject")

    if smtp_factory is None:
        return ToolResult(
            ok=False,
            error="SMTP not configured; agent should fall back to copy/paste flow",
            data={"to": to, "subject": subject, "attachments": attachments},
        )

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body or "(empty body)")
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=Path(path).name)
        except OSError as e:
            return ToolResult(ok=False, error=f"attachment failed: {e}")

    try:
        smtp = smtp_factory()
        try:
            smtp.send_message(msg)
        finally:
            with _suppress():
                smtp.quit()
    except smtplib.SMTPException as e:
        return ToolResult(ok=False, error=f"smtp error: {e}")
    return ToolResult(ok=True, data={"to": to, "subject": subject})


def wait(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``wait(ms)`` — bounded sleep (max 30s)."""
    _ = driver
    _ = bundle_dir
    try:
        ms = int(args.get("ms", 0))
    except (TypeError, ValueError):
        return ToolResult(ok=False, error="ms must be an int")
    ms = max(0, min(ms, 30_000))
    time.sleep(ms / 1000.0)
    return ToolResult(ok=True, data={"slept_ms": ms})


def done(driver: Any, args: dict[str, Any], bundle_dir: Path) -> ToolResult:
    """``done(result, reason)`` — terminate the loop. Caller breaks out."""
    _ = driver
    _ = bundle_dir
    result = str(args.get("result", "") or args.get("status", "") or "")
    reason = str(args.get("reason", "")).strip() or None
    if not result:
        return ToolResult(ok=False, error="missing result code")
    if not result.startswith("RESULT:"):
        result = f"RESULT:{result.lstrip(':')}"
    code, parsed_reason = parse_result_line(result)
    final_reason = reason or parsed_reason
    return ToolResult(
        ok=True,
        data={"terminal": True, "code": code, "reason": final_reason, "raw": result},
    )


# ---------------------------------------------------------------------------
# Registry + dispatch
# ---------------------------------------------------------------------------


TOOL_NAMES: tuple[str, ...] = (
    "navigate",
    "read_page",
    "screenshot",
    "click",
    "fill_form",
    "select",
    "upload",
    "tabs",
    "solve_captcha",
    "send_email",
    "wait",
    "done",
)


def get_tool_specs() -> list[dict[str, Any]]:
    """Return JSON-function-call schemas for the 12 tools (LLM tool registry)."""
    return [
        {
            "name": "navigate",
            "description": "Navigate the browser to a URL.",
            "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        },
        {
            "name": "read_page",
            "description": "Return a simplified DOM snapshot.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "screenshot",
            "description": "Save a PNG screenshot to the bundle dir.",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        },
        {
            "name": "click",
            "description": "Click the element matching ref (CSS/XPath/data-testid).",
            "parameters": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"]},
        },
        {
            "name": "fill_form",
            "description": "Batch-fill form fields: {ref: value}.",
            "parameters": {"type": "object", "properties": {"fields": {"type": "object"}}, "required": ["fields"]},
        },
        {
            "name": "select",
            "description": "Choose an option in a <select> or custom dropdown.",
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string"}, "value": {"type": "string"}},
                "required": ["ref", "value"],
            },
        },
        {
            "name": "upload",
            "description": "Upload a file via an input[type=file].",
            "parameters": {
                "type": "object",
                "properties": {"ref": {"type": "string"}, "path": {"type": "string"}},
                "required": ["ref", "path"],
            },
        },
        {
            "name": "tabs",
            "description": "List or switch browser tabs.",
            "parameters": {
                "type": "object",
                "properties": {"action": {"type": "string"}, "idx": {"type": "integer"}},
                "required": ["action"],
            },
        },
        {
            "name": "solve_captcha",
            "description": "Detect, solve, and inject a CAPTCHA token. Mandatory before form submit.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "name": "send_email",
            "description": "Email a resume to the recruiter (email-only postings).",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "attachments": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["to", "subject"],
            },
        },
        {
            "name": "wait",
            "description": "Sleep ``ms`` milliseconds (max 30s).",
            "parameters": {"type": "object", "properties": {"ms": {"type": "integer"}}, "required": ["ms"]},
        },
        {
            "name": "done",
            "description": "Terminate the loop with a RESULT:<CODE>[:reason] string.",
            "parameters": {
                "type": "object",
                "properties": {"result": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["result"],
            },
        },
    ]


def dispatch_tool(
    name: str,
    args: dict[str, Any],
    *,
    driver: Any,
    bundle_dir: Path,
    solver: CaptchaSolver | None = None,
    smtp_factory: Any = None,
    screenshot_idx: int = 0,
) -> ToolResult:
    """Invoke a tool by name. Always returns a :class:`ToolResult`."""
    args = args or {}
    if name == "navigate":
        return navigate(driver, args, bundle_dir)
    if name == "read_page":
        return read_page(driver, args, bundle_dir)
    if name == "screenshot":
        return screenshot(driver, args, bundle_dir, idx=screenshot_idx)
    if name == "click":
        return click(driver, args, bundle_dir)
    if name == "fill_form":
        return fill_form(driver, args, bundle_dir)
    if name == "select":
        return select(driver, args, bundle_dir)
    if name == "upload":
        return upload(driver, args, bundle_dir)
    if name == "tabs":
        return tabs(driver, args, bundle_dir)
    if name == "solve_captcha":
        return solve_captcha(driver, args, bundle_dir, solver=solver)
    if name == "send_email":
        return send_email(driver, args, bundle_dir, smtp_factory=smtp_factory)
    if name == "wait":
        return wait(driver, args, bundle_dir)
    if name == "done":
        return done(driver, args, bundle_dir)
    return ToolResult(ok=False, error=f"unknown tool {name!r}")


def append_transcript(bundle_dir: Path, entry: dict[str, Any]) -> None:
    """Append a JSON line to ``transcript.jsonl``."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False)
    with open(bundle_dir / "transcript.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")


class _suppress:
    """Tiny context manager — equivalent to ``contextlib.suppress(Exception)``.

    Inlined so this module doesn't pull contextlib into the hot path.
    """

    def __enter__(self) -> _suppress:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None


__all__ = [
    "TOOL_NAMES",
    "ToolResult",
    "append_transcript",
    "click",
    "dispatch_tool",
    "done",
    "fill_form",
    "get_tool_specs",
    "navigate",
    "read_page",
    "screenshot",
    "select",
    "send_email",
    "simplify_dom",
    "solve_captcha",
    "tabs",
    "upload",
    "wait",
]
