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

router = APIRouter()


def _openclaw_status() -> dict[str, Any]:
    """Best-effort OpenClaw heartbeat status: last-tick timestamp + channel."""
    tick_file = nexscout_dir() / "last-tick.json"
    if not tick_file.exists():
        return {"last_tick": None, "channel": None}
    try:
        data = json.loads(tick_file.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {"last_tick": None, "channel": None}
    return {"last_tick": data.get("ts"), "channel": data.get("channel")}


def _recent_events(limit: int = 20) -> list[dict[str, Any]]:
    conn = init_db()
    rows = conn.execute("SELECT ts, kind, payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    conn = init_db()
    stats = get_stats(conn)
    events = _recent_events()
    openclaw = _openclaw_status()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": stats,
            "events": events,
            "openclaw": openclaw,
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
