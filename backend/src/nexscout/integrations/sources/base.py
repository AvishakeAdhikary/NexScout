"""Source adapter contract for opportunity discovery (spec §6.2).

Every adapter declares what it can do and under which terms. The registry never assumes a
source supports scraping or unrestricted access. Adapters return raw records plus a cursor,
and `normalize` maps each record to `NormalizedOpportunity` (unknown values stay None).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from nexscout.domain.opportunities import NormalizedOpportunity, OpportunityKind


@dataclass(frozen=True)
class SourceCapabilities:
    kinds: frozenset[OpportunityKind]
    supports_keywords: bool
    supports_location: bool
    pagination: str  # "cursor" | "page" | "none"
    auth: str  # "none" | "api_key" | "oauth" | "user_session"
    rate_limit: str
    terms: str
    incremental: str  # how new/changed records are detected
    limitations: tuple[str, ...] = ()
    is_demo_data: bool = False


@dataclass(frozen=True)
class SourceQuery:
    kinds: frozenset[OpportunityKind]
    keywords: tuple[str, ...] = ()
    locations: tuple[str, ...] = ()


@dataclass
class SourcePage:
    records: list[dict[str, Any]]
    next_cursor: str | None = None


@dataclass
class SourceSettings:
    values: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    key: str
    name: str
    capabilities: SourceCapabilities

    async def fetch(
        self, query: SourceQuery, cursor: str | None, settings: SourceSettings
    ) -> SourcePage: ...

    def normalize(self, record: dict[str, Any]) -> NormalizedOpportunity: ...


def content_hash(opp: NormalizedOpportunity) -> str:
    """Stable hash of the normalized content, used to detect changed postings on re-sync."""
    payload = opp.model_dump(mode="json", exclude={"source_url"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def query_hash(query: SourceQuery) -> str:
    payload = {
        "kinds": sorted(k.value for k in query.kinds),
        "keywords": sorted(query.keywords),
        "locations": sorted(query.locations),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]
