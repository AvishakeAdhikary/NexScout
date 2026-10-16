"""Shared fixtures. DB-backed tests need PostgreSQL (see docs/TESTING.md).

If the database is unreachable, DB tests are *skipped* with an explicit reason, unless
NEXSCOUT_REQUIRE_DB=1 (CI), in which case they fail.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from nexscout.config import Settings

TEST_DB_URL = os.environ.get(
    "NEXSCOUT_TEST_DATABASE_URL",
    "postgresql+psycopg://nexscout_app:nexscout_app_dev@127.0.0.1:5432/nexscout_test",
)
TEST_MIGRATION_DB_URL = os.environ.get(
    "NEXSCOUT_TEST_MIGRATION_DATABASE_URL",
    "postgresql+psycopg://nexscout_owner:nexscout_owner_dev@127.0.0.1:5432/nexscout_test",
)
REQUIRE_DB = os.environ.get("NEXSCOUT_REQUIRE_DB") == "1"

# Tables truncated between tests (children first is not needed with CASCADE).
DATA_TABLES = ("audit_events", "candidate_cases", "sessions", "login_attempts", "users")


if sys.platform == "win32":

    def pytest_asyncio_loop_factories(config: Any, item: Any) -> dict[str, Any]:
        # psycopg async cannot use the Windows ProactorEventLoop.
        return {"selector": asyncio.SelectorEventLoop}


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "env": "test",
        "database_url": TEST_DB_URL,
        "migration_database_url": TEST_MIGRATION_DB_URL,
        "log_json": False,
        "log_level": "WARNING",
        "db_pool_size": 5,
    }
    base.update(overrides)
    return Settings(**base)


_db_probe: dict[str, str | None] = {}


def _db_unreachable_reason() -> str | None:
    """Probe once per session; a refused localhost connect is slow on Windows."""
    if "reason" not in _db_probe:
        probe = create_engine(TEST_MIGRATION_DB_URL, connect_args={"connect_timeout": 3})
        try:
            with probe.connect() as conn:
                conn.execute(text("SELECT 1"))
            _db_probe["reason"] = None
        except Exception as exc:  # noqa: BLE001
            _db_probe["reason"] = (
                f"PostgreSQL test database unreachable ({type(exc).__name__}). See docs/TESTING.md"
            )
        finally:
            probe.dispose()
    return _db_probe["reason"]


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    reason = _db_unreachable_reason()
    if reason:
        if REQUIRE_DB:
            pytest.fail(reason)
        pytest.skip(reason)
    engine = create_engine(TEST_MIGRATION_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_db(owner_engine: Engine) -> Engine:
    """Fresh schema: downgrade to base then upgrade to head (also exercises downgrades)."""
    from alembic import command

    from nexscout.infrastructure.db.migrations import alembic_config

    cfg = alembic_config(TEST_MIGRATION_DB_URL)
    with owner_engine.begin() as conn:
        exists = conn.execute(text("SELECT to_regclass('alembic_version')")).scalar()
    if exists:
        command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return owner_engine


@pytest.fixture
def clean_db(migrated_db: Engine) -> Iterator[Engine]:
    yield migrated_db
    with migrated_db.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(DATA_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    path = tmp_path / "storage"
    path.mkdir()
    return path


@pytest.fixture
async def app(clean_db: Engine, storage_dir: Path) -> AsyncIterator[Any]:
    from nexscout.api.app import create_app

    application = create_app(make_settings(storage_dir=storage_dir))
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


@pytest.fixture
async def other_client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    """A second, independent browser (separate cookie jar) for cross-tenant tests."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c
