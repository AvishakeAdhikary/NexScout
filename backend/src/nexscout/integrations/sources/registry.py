"""Registry of available source adapters.

Labelled demo sources are registered only when demo data is on (`NEXSCOUT_DEMO_DATA=1`: tests,
E2E, developer demos). A shipped install never lists them.
"""

from __future__ import annotations

from functools import lru_cache

from nexscout.config import get_settings
from nexscout.integrations.sources.base import SourceAdapter
from nexscout.integrations.sources.fixture import fixture_sources


@lru_cache(maxsize=2)
def _adapters(demo: bool) -> dict[str, SourceAdapter]:
    found: list[SourceAdapter] = []
    if demo:
        found.extend(fixture_sources())
    return {a.key: a for a in found}


def adapters() -> dict[str, SourceAdapter]:
    return _adapters(get_settings().demo_data)


def get_adapter(key: str) -> SourceAdapter | None:
    return adapters().get(key)
