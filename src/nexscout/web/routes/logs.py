"""Live backend logs viewer.

Tails the shared per-role log files written by :mod:`nexscout.core.logsetup`
(``autopilot`` / ``web`` / ``mcp``) so the user can watch exactly what the
backend is doing. Full-page request renders ``logs.html``; the HTMX poll returns
the ``_logs_view.html`` fragment.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ...core.logsetup import ROLES, tail

router = APIRouter()


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, role: str = "autopilot") -> HTMLResponse:
    if role not in ROLES:
        role = "autopilot"
    context = {"role": role, "roles": ROLES, "lines": tail(role, 400)}
    template = "_logs_view.html" if request.headers.get("HX-Request") else "logs.html"
    return request.app.state.templates.TemplateResponse(request, template, context)


__all__ = ["router"]
