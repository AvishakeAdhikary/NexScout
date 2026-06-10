"""Pause / resume / run controls.

The "run" action (historically the CLI ``tick``: discover → enrich → score →
tailor → apply) can take minutes. It runs in a background thread so the
request returns immediately; the UI shows a spinner and polls
``GET /controls/status`` until it finishes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...core.config import nexscout_dir
from .. import runner

router = APIRouter(prefix="/controls")


def _pause_path() -> str:
    return str(nexscout_dir() / "paused.flag")


def _is_paused() -> bool:
    return Path(_pause_path()).exists()


@router.post("/pause")
async def pause() -> JSONResponse:
    with open(_pause_path(), "w", encoding="utf-8") as f:
        f.write(datetime.now(UTC).isoformat())
    return JSONResponse({"status": "paused", "paused": True})


@router.post("/resume")
async def resume() -> JSONResponse:
    Path(_pause_path()).unlink(missing_ok=True)
    return JSONResponse({"status": "resumed", "paused": False})


@router.post("/tick")
async def tick() -> JSONResponse:
    """Start a "check for new jobs" run in the background and return at once.

    Returns ``202 Accepted`` immediately — the long work happens off-thread so
    the browser is never blocked. Poll :func:`status` to watch progress.
    """
    status = runner.start_run()
    return JSONResponse(
        {"status": "started", "running": status.running, "message": status.message},
        status_code=202,
    )


# Friendly alias — the dashboard's primary button posts here.
@router.post("/run")
async def run_now() -> JSONResponse:
    return await tick()


@router.get("/status")
async def status() -> JSONResponse:
    """Current background-run status for HTMX polling (and tooling)."""
    snapshot = runner.get_status()
    payload = snapshot.to_dict()
    payload["paused"] = _is_paused()
    return JSONResponse(payload)


__all__ = ["router"]
