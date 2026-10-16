"""Deterministic fixture sources bundled for development, tests, and demos.

They are clearly labelled as demo data (`is_demo_data=True`). The UI shows that label, and they
must never be presented as real postings. The data deliberately contains cross-source
duplicates, tracking-parameter URL variants, distinct requisitions with identical titles, closed
postings, and a "later postings" set that exercises incremental sync.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from nexscout.domain.opportunities import NormalizedOpportunity, OpportunityKind
from nexscout.integrations.sources.base import (
    SourceCapabilities,
    SourcePage,
    SourceQuery,
    SourceSettings,
)

DATA_DIR = Path(__file__).parent / "fixtures"
PAGE_SIZE = 3

_DEMO_TERMS = "Synthetic demo data bundled with NexScout. These are not real postings."


@lru_cache(maxsize=8)
def _load(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((DATA_DIR / name).read_text(encoding="utf-8"))
    return data


def _matches(record: dict[str, Any], query: SourceQuery) -> bool:
    if OpportunityKind(record["kind"]) not in query.kinds:
        return False
    if query.keywords:
        text = " ".join(
            [
                record.get("title", ""),
                record.get("description", ""),
                " ".join(record.get("research_areas", [])),
            ]
        ).lower()
        if not any(k.lower() in text for k in query.keywords):
            return False
    return True


class FixtureSource:
    """Paginated (cursor = offset) local source over a bundled JSON file."""

    def __init__(
        self,
        key: str,
        name: str,
        files: tuple[str, ...],
        later_file: str | None,
        kinds: frozenset[OpportunityKind],
    ) -> None:
        self.key = key
        self.name = name
        self._files = files
        self._later_file = later_file
        self.capabilities = SourceCapabilities(
            kinds=kinds,
            supports_keywords=True,
            supports_location=False,
            pagination="cursor",
            auth="none",
            rate_limit="Not applicable (local data)",
            terms=_DEMO_TERMS,
            incremental="Content hash per listing id; unchanged listings are skipped.",
            limitations=("Demo data only.",),
            is_demo_data=True,
        )

    def _records(self, settings: SourceSettings) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for name in self._files:
            records.extend(_load(name))
        if self._later_file and settings.values.get("include_later_postings"):
            later = {r["external_id"]: r for r in _load(self._later_file)}
            records = [later.pop(r["external_id"], r) for r in records] + list(later.values())
        return records

    async def fetch(
        self, query: SourceQuery, cursor: str | None, settings: SourceSettings
    ) -> SourcePage:
        matching = [r for r in self._records(settings) if _matches(r, query)]
        start = int(cursor or 0)
        page = matching[start : start + PAGE_SIZE]
        nxt = start + PAGE_SIZE
        return SourcePage(records=page, next_cursor=str(nxt) if nxt < len(matching) else None)

    def normalize(self, record: dict[str, Any]) -> NormalizedOpportunity:
        payload = {k: v for k, v in record.items() if not k.startswith("_")}
        payload["source_key"] = self.key
        return NormalizedOpportunity.model_validate(payload)


def fixture_sources() -> list[FixtureSource]:
    jobs = frozenset({OpportunityKind.JOB})
    academic = frozenset(
        {
            OpportunityKind.PHD,
            OpportunityKind.POSTDOC,
            OpportunityKind.RESEARCH_ASSISTANT,
            OpportunityKind.SCHOLARSHIP,
        }
    )
    return [
        FixtureSource("demo_jobs_board_a", "Demo job board A", ("jobs_board_a.json",), None, jobs),
        FixtureSource(
            "demo_jobs_board_b",
            "Demo job board B",
            ("jobs_board_b.json",),
            "jobs_board_b_later.json",
            jobs,
        ),
        FixtureSource(
            "demo_academic_portal", "Demo academic portal", ("academic.json",), None, academic
        ),
    ]
