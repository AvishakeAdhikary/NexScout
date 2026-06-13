"""Pause / resume / stop / run controls + the live, interactive pipeline panel.

The autopilot, web, and MCP are **separate processes**, so control flows through
the shared ``pipeline-control.json`` (read by the autopilot) and live status is
read from ``pipeline-status.json`` (written by whatever runs a pass). See
``core/pipeline_status.py``.

* ``/controls/pipeline`` + ``/controls/pipeline/*`` power the interactive
  dashboard panel — they return the panel HTML so a click updates it at once.
* The older JSON endpoints (``/controls/pause`` etc.) remain for tooling/tests
  and now write the *real* control flags, so Pause finally stops the autopilot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ...core import pipeline_status as ps
from ...core.database import init_db
from ...core.profile import Profile
from .. import runner

router = APIRouter(prefix="/controls")

#: Friendly label + one-line explanation for each pipeline stage.
STAGE_META: dict[str, tuple[str, str]] = {
    "discover": ("Discover", "Search the job boards for new postings."),
    "enrich": ("Read details", "Open each posting and pull its full description."),
    "score": ("Score", "Rate how well each job matches you (0–10)."),
    "tailor": ("Tailor résumé", "Rewrite your résumé for each good match."),
    "cover": ("Cover letter", "Write a cover letter where the job needs one."),
    "render": ("Make PDFs", "Turn the tailored résumé / cover letter into PDFs."),
    "apply": ("Apply", "Open the application form and submit it for you."),
}


def _is_paused() -> bool:
    return ps.is_paused()


def _panel_context() -> dict[str, Any]:
    backlog: dict[str, int] = {}
    try:
        profile = Profile.from_path()
        conn = init_db()
        backlog = ps.backlog_counts(
            conn,
            min_score=profile.search.min_score,
            always_cover=profile.apply.always_cover_letter,
        )
    except Exception:  # never let the panel crash the dashboard
        backlog = {}
    return {
        "status": ps.read_status(),
        "control": ps.read_control(),
        "backlog": backlog,
        "stage_meta": STAGE_META,
        "stages": list(ps.STAGES),
        "run_status": runner.get_status().to_dict(),
    }


def _panel(request: Request) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, "_pipeline_panel.html", _panel_context())


# --------------------------------------------------------------------------- #
# Interactive panel (returns HTML)
# --------------------------------------------------------------------------- #


@router.get("/pipeline", response_class=HTMLResponse)
async def pipeline_panel(request: Request) -> HTMLResponse:
    return _panel(request)


@router.post("/pipeline/pause", response_class=HTMLResponse)
async def panel_pause(request: Request) -> HTMLResponse:
    ps.set_paused(True)
    return _panel(request)


@router.post("/pipeline/resume", response_class=HTMLResponse)
async def panel_resume(request: Request) -> HTMLResponse:
    ps.set_paused(False)
    return _panel(request)


@router.post("/pipeline/stop", response_class=HTMLResponse)
async def panel_stop(request: Request) -> HTMLResponse:
    ps.request_stop()
    return _panel(request)


@router.post("/pipeline/run", response_class=HTMLResponse)
async def panel_run(request: Request) -> HTMLResponse:
    runner.start_run()
    return _panel(request)


@router.post("/pipeline/stage/{stage}/toggle", response_class=HTMLResponse)
async def panel_toggle_stage(request: Request, stage: str) -> HTMLResponse:
    if stage in ps.ALL_STEPS:
        ps.set_stage_enabled(stage, not ps.stage_enabled(stage))
    return _panel(request)


# --------------------------------------------------------------------------- #
# Legacy JSON control endpoints (tooling + tests) — now write the real flags
# --------------------------------------------------------------------------- #


@router.post("/pause")
async def pause() -> JSONResponse:
    ps.set_paused(True)
    return JSONResponse({"status": "paused", "paused": True})


@router.post("/resume")
async def resume() -> JSONResponse:
    ps.set_paused(False)
    return JSONResponse({"status": "resumed", "paused": False})


@router.post("/stop")
async def stop() -> JSONResponse:
    ps.request_stop()
    return JSONResponse({"status": "stopping"})


@router.post("/tick")
async def tick() -> JSONResponse:
    """Start a full pass in the background and return at once (202)."""
    status = runner.start_run()
    return JSONResponse(
        {"status": "started", "running": status.running, "message": status.message},
        status_code=202,
    )


@router.post("/run")
async def run_now() -> JSONResponse:
    return await tick()


@router.get("/status")
async def status() -> JSONResponse:
    """Background-run snapshot + live pipeline status, for HTMX polling/tooling."""
    snapshot = runner.get_status()
    payload = snapshot.to_dict()
    payload["paused"] = _is_paused()
    payload["pipeline"] = ps.read_status()
    payload["control"] = ps.read_control()
    return JSONResponse(payload)


__all__ = ["router"]
