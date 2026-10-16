"""Registry of available source adapters. Live adapters are added here as they are verified."""

from __future__ import annotations

from functools import lru_cache

from nexscout.integrations.sources.base import SourceAdapter
from nexscout.integrations.sources.fixture import fixture_sources


@lru_cache(maxsize=1)
def adapters() -> dict[str, SourceAdapter]:
    found: list[SourceAdapter] = [*fixture_sources()]
    return {a.key: a for a in found}


def get_adapter(key: str) -> SourceAdapter | None:
    return adapters().get(key)
