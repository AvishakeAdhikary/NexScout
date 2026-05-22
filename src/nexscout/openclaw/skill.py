"""Slash-command handlers for OpenClaw.

OpenClaw delivers slash commands as ``(name, args)`` pairs. Each handler
returns a small dict the OpenClaw runtime renders into the channel.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Any

from ..core.database import get_stats, init_db
from ..core.profile import Profile

#: Mapping ``command → handler`` populated below.
SkillHandler = Callable[..., dict[str, Any]]


def handle_status(*, profile: Profile | None = None) -> dict[str, Any]:
    """``/nexscout status`` — pipeline stats + last 5 events."""
    _ = profile
    conn = init_db()
    stats = get_stats(conn)
    events = [
        dict(r) for r in conn.execute("SELECT ts, kind, payload_json FROM events ORDER BY id DESC LIMIT 5").fetchall()
    ]
    line = (
        f"total={stats['total']} scored={stats['scored']} "
        f"tailored={stats['tailored']} applied={stats['applied']} "
        f"ready={stats['ready_to_apply']} errors={stats['apply_errors']}"
    )
    return {"text": line, "events": events}


def handle_apply(url: str, *, workers: int = 1, profile: Profile | None = None) -> dict[str, Any]:
    """``/nexscout apply <url>`` — one-shot apply."""
    _ = profile
    return {
        "text": f"Queued apply for {url}",
        "command": ["nexscout", "apply", "--url", url, "--workers", str(workers)],
    }


def handle_pause(*, profile: Profile | None = None) -> dict[str, Any]:
    _ = profile
    return {"text": "paused", "command": ["nexscout", "controls", "pause"]}


def handle_resume(*, profile: Profile | None = None) -> dict[str, Any]:
    _ = profile
    return {"text": "resumed", "command": ["nexscout", "controls", "resume"]}


def handle_question(*, profile: Profile | None = None) -> dict[str, Any]:
    """``/nexscout question`` — list pending questions."""
    _ = profile
    conn = init_db()
    rows = conn.execute(
        "SELECT id, question, asked_at FROM pending_questions WHERE answered_at IS NULL ORDER BY id"
    ).fetchall()
    items = [dict(r) for r in rows]
    if not items:
        return {"text": "no pending questions"}
    body = "\n".join(f"#{r['id']}: {r['question']}" for r in items)
    return {"text": body, "items": items}


def handle_answer(question: str, reply: str, *, profile: Profile | None = None) -> dict[str, Any]:
    """``/nexscout answer "<q>" "<a>"`` — answer + persist to memory."""
    _ = profile
    from datetime import UTC, datetime

    from .memory import append_learned_answer

    conn = init_db()
    now = datetime.now(UTC).isoformat()
    row = conn.execute(
        "SELECT id, job_url FROM pending_questions WHERE answered_at IS NULL AND question = ? ORDER BY id LIMIT 1",
        (question,),
    ).fetchone()
    if row is None:
        # No exact-match question — still persist to memory for future use.
        append_learned_answer(question, reply, ts=now, source="openclaw")
        return {"text": "answer recorded (no matching pending question)"}
    conn.execute(
        "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
        (reply, now, row["id"]),
    )
    if row["job_url"]:
        conn.execute(
            "UPDATE jobs SET apply_status=NULL WHERE url=? AND apply_status='paused_for_question'",
            (row["job_url"],),
        )
    append_learned_answer(question, reply, ts=now, source="openclaw")
    return {"text": f"answered #{row['id']}"}


HANDLERS: dict[str, SkillHandler] = {
    "status": handle_status,
    "apply": handle_apply,
    "pause": handle_pause,
    "resume": handle_resume,
    "question": handle_question,
    "answer": handle_answer,
}


def dispatch(name: str, raw_args: str | list[str], *, profile: Profile | None = None) -> dict[str, Any]:
    """Dispatch ``/nexscout <name> <args>`` to the right handler.

    ``raw_args`` may be a list of pre-split tokens or a single string (the
    function will ``shlex.split`` it).
    """
    handler = HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown command: {name!r}", "available": sorted(HANDLERS)}
    args = list(raw_args) if isinstance(raw_args, list) else shlex.split(raw_args or "")
    try:
        return handler(*args, profile=profile)
    except TypeError as e:
        return {"error": f"bad args for /{name}: {e}"}


__all__ = ["HANDLERS", "SkillHandler", "dispatch"]
