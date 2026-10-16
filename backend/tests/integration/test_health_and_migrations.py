import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine

from nexscout.infrastructure.db import models  # noqa: F401
from nexscout.infrastructure.db.base import Base
from nexscout.infrastructure.db.migrations import include_object

pytestmark = pytest.mark.db


async def test_healthz(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-request-id"]


async def test_readyz_reports_db_and_migrations(client: httpx.AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok", "database": "ok", "migrations": "ok"}


def test_models_match_migrations(migrated_db: Engine) -> None:
    """Fails if an ORM model changed without a matching Alembic revision."""
    with migrated_db.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"include_object": include_object}),
            Base.metadata,
        )
    assert diff == [], f"Schema drift between models and migrations: {diff}"
