"""Pause / resume / tick controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ...core.config import nexscout_dir

router = APIRouter(prefix="/controls")


def _pause_path() -> str:
    return str(nexscout_dir() / "paused.flag")


@router.post("/pause")
async def pause() -> JSONResponse:
    with open(_pause_path(), "w", encoding="utf-8") as f:
        f.write(datetime.now(UTC).isoformat())
    return JSONResponse({"status": "paused"})


@router.post("/resume")
async def resume() -> JSONResponse:
    from pathlib import Path

    Path(_pause_path()).unlink(missing_ok=True)
    return JSONResponse({"status": "resumed"})


@router.post("/tick")
async def tick() -> JSONResponse:
    from ...core.profile import Profile
    from ...openclaw.tick import run as tick_run

    profile = Profile.from_path()
    summary = tick_run(profile=profile)
    # Persist a small marker so the dashboard can show "last tick" without
    # walking the events table.
    p = nexscout_dir() / "last-tick.json"
    p.write_text(
        json.dumps({"ts": datetime.now(UTC).isoformat(), "summary": summary}),
        encoding="utf-8",
    )
    return JSONResponse({"status": "ticked", "summary": summary})


__all__ = ["router"]
