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
