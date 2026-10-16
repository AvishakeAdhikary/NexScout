"""Request-scoped dependencies: DB unit of work, authenticated actor, CSRF enforcement."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexscout.application.actor import Actor
from nexscout.application.auth import csrf_valid, resolve_session
from nexscout.config import Settings
from nexscout.domain.errors import AuthenticationFailed, PermissionDenied
from nexscout.infrastructure.db.engine import bind_tenant
from nexscout.infrastructure.storage import ObjectStore

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request. Commits on success, rolls back on any exception.

    Registered with scope="function" so the commit happens *before* the response is sent.
    """
    maker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]


def get_object_store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.object_store
    return store


ObjectStoreDep = Annotated[ObjectStore, Depends(get_object_store)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def get_actor(request: Request, session: DbSession, settings: SettingsDep) -> Actor:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise AuthenticationFailed("Please sign in.")
    resolved = await resolve_session(
        session,
        settings,
        token,
        ip=client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )
    if request.method not in SAFE_METHODS and not csrf_valid(
        resolved, request.headers.get(settings.csrf_header_name)
    ):
        raise PermissionDenied("Missing or invalid CSRF token. Reload the page and try again.")
    # Bind the tenant for Postgres RLS for the rest of this transaction.
    await bind_tenant(session, resolved.actor.user_id)
    return resolved.actor


CurrentActor = Annotated[Actor, Depends(get_actor, scope="function")]
