"""FastAPI application factory (§17).

Sets up:

* Static + Jinja2 (default delimiters, not the LaTeX ones).
* Session middleware (HMAC signed) and CSRF helpers.
* Route mounting.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth as web_auth
from .filters import humandate
from .routes import api as api_routes
from .routes import applications as application_routes
from .routes import controls as controls_routes
from .routes import dashboard as dashboard_routes
from .routes import jobs as jobs_routes
from .routes import logs as logs_routes
from .routes import profile as profile_routes
from .routes import questions as questions_routes


def _templates_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Build and return the FastAPI app."""
    app = FastAPI(title="NexScout", docs_url=None, redoc_url=None)
    from ..core.logsetup import setup_file_logging

    setup_file_logging("web")
    templates_dir = _templates_dir()
    static_dir = _static_dir()
    templates_dir.mkdir(parents=True, exist_ok=True)
    static_dir.mkdir(parents=True, exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))
    templates.env.filters["humandate"] = humandate
    app.state.templates = templates
    app.state.auth = web_auth.build_auth()

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.exception_handler(404)
    async def _not_found(_request: Request, _exc: Any) -> HTMLResponse:
        return HTMLResponse("<h1>404 — not found</h1>", status_code=404)

    # Mount routers.
    app.include_router(dashboard_routes.router)
    app.include_router(jobs_routes.router)
    app.include_router(application_routes.router)
    app.include_router(profile_routes.router)
    app.include_router(questions_routes.router)
    app.include_router(logs_routes.router)
    app.include_router(controls_routes.router)
    app.include_router(api_routes.router)
    # Top-level /metrics alias (Prometheus convention) in addition to /api/metrics.
    app.include_router(api_routes.top_router)
    return app


__all__ = ["create_app"]
