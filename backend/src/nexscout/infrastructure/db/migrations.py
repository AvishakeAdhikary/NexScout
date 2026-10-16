"""Helpers to locate Alembic config and compute the expected migration head."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    if database_url:
        cfg.attributes["database_url"] = database_url
    return cfg


@lru_cache(maxsize=1)
def expected_head() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


async def setup_checkpointer(owner_url: str) -> None:
    """Create/upgrade LangGraph checkpoint tables (as owner) and grant the worker role."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    dsn = owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    async with await AsyncConnection.connect(
        dsn, autocommit=True, prepare_threshold=0, row_factory=dict_row
    ) as conn:
        await AsyncPostgresSaver(conn).setup()
        await conn.execute(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nexscout_system') "
            "THEN GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, "
            "checkpoint_writes, checkpoint_migrations TO nexscout_system; END IF; END $$"
        )


EXTERNAL_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)


def include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Autogenerate filter: LangGraph's checkpoint tables are managed by `saver.setup()`."""
    table = getattr(obj, "table", None)
    table_name = getattr(table, "name", None) if type_ != "table" else name
    return table_name not in EXTERNAL_TABLES
