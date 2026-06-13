"""Live backend logs viewer.

Streams the shared per-role log files written by :mod:`nexscout.core.logsetup`
(``autopilot`` / ``web`` / ``mcp``). Loading is **incremental**: the page renders
the recent tail once, then a poll fetches only the bytes appended since the last
offset (so it never re-sends the whole file). Supports a min-level filter and a
"clear" that resets the view to the current end without touching the file.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.logsetup import ROLES, file_size, read_since, tail

router = APIRouter()

_LEVEL_CHOICES = ("ALL", "INFO", "WARNING", "ERROR")


def _norm(role: str | None, level: str | None) -> tuple[str, str]:
    r = role if role in ROLES else "autopilot"
    lv = level if level in _LEVEL_CHOICES else "ALL"
    return r, lv


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, role: str = "autopilot", level: str = "ALL") -> HTMLResponse:
    role, level = _norm(role, level)
    context = {
        "role": role,
        "roles": ROLES,
        "level": level,
        "levels": _LEVEL_CHOICES,
        "lines": tail(role, 300, None if level == "ALL" else level),
        "offset": file_size(role),
    }
    return request.app.state.templates.TemplateResponse(request, "logs.html", context)


@router.get("/logs/tail", response_class=HTMLResponse)
async def logs_tail(request: Request, role: str = "autopilot", level: str = "ALL", offset: int = 0) -> HTMLResponse:
    """Return only the lines appended since ``offset`` (+ an OOB offset update)."""
    role, level = _norm(role, level)
    lines, new_offset = read_since(role, offset, None if level == "ALL" else level)
    return request.app.state.templates.TemplateResponse(
        request, "_logs_append.html", {"lines": lines, "offset": new_offset}
    )


@router.post("/logs/clear", response_class=HTMLResponse)
async def logs_clear(request: Request, role: str = "autopilot", level: str = "ALL") -> HTMLResponse:
    """Clear the *view* (not the file): empty the pane and resume tailing from
    the current end. Cross-process file truncation is racy, so this just moves
    the viewer's baseline forward — race-free and instant."""
    role, level = _norm(role, level)
    return request.app.state.templates.TemplateResponse(
        request, "_logs_append.html", {"lines": [], "offset": file_size(role), "cleared": True}
    )


__all__ = ["router"]
