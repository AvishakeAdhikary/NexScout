"""Dashboard route (`GET /`) — counters + score distribution + events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.config import nexscout_dir
from ...core.database import get_stats, init_db
from ...core.errors import ConfigError
from ...core.profile import Profile

router = APIRouter()


def _openclaw_status() -> dict[str, Any]:
    """Best-effort OpenClaw heartbeat status: last-tick timestamp + channel."""
    tick_file = nexscout_dir() / "last-tick.json"
    channel = _profile_channel()
    if not tick_file.exists():
        return {"last_tick": None, "channel": channel, "questions": None, "channel_delivered": None}
    try:
        data = json.loads(tick_file.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {"last_tick": None, "channel": channel, "questions": None, "channel_delivered": None}
    # Prefer the profile-declared channel over whatever the marker happens
    # to record (the profile is the source of truth).
    return {
        "last_tick": data.get("ts"),
        "channel": channel or data.get("channel"),
        "questions": data.get("questions"),
        "channel_delivered": data.get("channel_delivered"),
    }


def _profile_channel() -> str | None:
    try:
        return Profile.from_path().openclaw.channel
    except (ConfigError, OSError, ValueError):
        return None
    except Exception:
        # Defensive: a malformed YAML can raise pydantic validation, broken
        # env vars can raise IO errors etc. Never let the dashboard crash.
        return None


def _recent_events(limit: int = 20) -> list[dict[str, Any]]:
    conn = init_db()
    rows = conn.execute("SELECT ts, kind, payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def _pending_telegram_count() -> int:
    """Count of pending_questions rows still awaiting channel delivery."""
    conn = init_db()
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM pending_questions WHERE answered_at IS NULL AND channel_delivered_at IS NULL"
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _score_distribution_svg(distribution: dict[int, int], *, width: int = 360, height: int = 120) -> str:
    """Render the score-distribution chart as an inline SVG.

    Renders an empty-but-still-valid SVG when ``distribution`` is empty so
    the dashboard never gates on having scored jobs.
    """
    if not distribution:
        return (
            f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="score-dist">'
            f'<rect width="{width}" height="{height}" fill="#f5f5f5"/>'
            f'<text x="{width // 2}" y="{height // 2}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="14" fill="#888">no scored jobs yet</text>'
            f"</svg>"
        )
    items = sorted(distribution.items(), key=lambda kv: kv[0])
    max_count = max(v for _, v in items) or 1
    pad = 24
    bar_area = width - 2 * pad
    bar_w = max(8, (bar_area // max(1, len(items))) - 6)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" class="score-dist">',
        f'<rect width="{width}" height="{height}" fill="#fafafa"/>',
    ]
    for idx, (score, count) in enumerate(items):
        bar_h = int((height - 32) * (count / max_count))
        x = pad + idx * (bar_w + 6)
        y = height - 18 - bar_h
        parts.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="#3a72ff" rx="2"/>')
        parts.append(
            f'<text x="{x + bar_w // 2}" y="{height - 4}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="11" fill="#333">{score}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w // 2}" y="{y - 3}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="11" fill="#333">{count}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    conn = init_db()
    stats = get_stats(conn)
    events = _recent_events()
    openclaw = _openclaw_status()
    pending_telegram = _pending_telegram_count()
    score_svg = _score_distribution_svg(stats.get("score_distribution") or {})
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "events": events,
            "openclaw": openclaw,
            "pending_telegram": pending_telegram,
            "score_distribution_svg": score_svg,
            "now": datetime.now().isoformat(timespec="seconds"),
        },
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# Helper used by tests that don't go through Jinja: keep tick file path local.
def write_last_tick(*, channel: str | None = None, root: Path | None = None) -> Path:
    """Persist a heartbeat marker the dashboard can display."""
    root = root or nexscout_dir()
    p = root / "last-tick.json"
    p.write_text(
        json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "channel": channel}),
        encoding="utf-8",
    )
    return p


__all__ = ["router", "write_last_tick"]
