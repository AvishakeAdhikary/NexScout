"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexscout import __version__
from nexscout.agent_runtime.events import EventHub
from nexscout.agent_runtime.worker import libpq_url
from nexscout.api.errors import install_error_handlers
from nexscout.api.middleware import RequestContextMiddleware
from nexscout.api.routers import (
    account,
    auth,
    cases,
    documents,
    health,
    mindmap,
    opportunities,
    profile,
    relationships,
    runs,
)
from nexscout.config import Settings, get_settings
from nexscout.infrastructure.db.engine import build_engine, build_sessionmaker
from nexscout.infrastructure.storage import LocalObjectStore
from nexscout.observability import configure_logging, get_logger

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    log = get_logger("nexscout.api")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = build_sessionmaker(engine)
        app.state.object_store = LocalObjectStore(settings.storage_dir)
        app.state.event_hub = EventHub(libpq_url(settings.database_url.get_secret_value()))
        await app.state.event_hub.start()
        log.info("api_started", env=settings.env, version=__version__)
        try:
            yield
        finally:
            await app.state.event_hub.stop()
            await engine.dispose()
            log.info("api_stopped")

    app = FastAPI(
        title="NexScout API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router, prefix=API_PREFIX)
    for module in (cases, profile, documents, relationships, account, mindmap, opportunities, runs):
        app.include_router(module.router, prefix=API_PREFIX)
    return app
