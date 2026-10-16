"""Async engine and transaction helpers that bind the tenant for Postgres RLS."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nexscout.config import Settings


def build_engine(settings: Settings, url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        url or settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_timeout=settings.db_pool_timeout_s,
        connect_args={"connect_timeout": settings.db_connect_timeout_s},
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def bind_tenant(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Set app.user_id for the *current transaction* only (safe with connection pooling)."""
    await session.execute(
        text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
    )


@asynccontextmanager
async def tenant_transaction(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: uuid.UUID
) -> AsyncIterator[AsyncSession]:
    """A committed-on-success transaction with RLS bound to `user_id` (used by workers)."""
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, user_id)
        yield session
