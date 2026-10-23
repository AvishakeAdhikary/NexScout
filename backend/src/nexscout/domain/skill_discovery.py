"""Checking skills an AI model proposed (ADR-0020). Plain code decides what reaches the user.

A proposal is kept only if:
- its quote appears, word for word (spacing and case aside), in the source it cites: one of
  the user's confirmed entries or one of their CV documents;
- the skill's name appears in that quote, so the skill is something the text actually says;
- the name looks like a skill (short, not a sentence or a fragment);
- the case doesn't have it already, and it isn't proposed twice.
Everything dropped is reported with its reason.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from nexscout.domain.cv_heuristics import is_plausible_skill
from nexscout.domain.profile import Section, identity_keys

MAX_PROPOSALS = 200


@dataclass(frozen=True)
class Proposal:
    name: str
    category: str | None
    quote: str
    source_id: str  # "fact:<uuid>" or "document:<uuid>"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


def verify_proposals(
    proposals: list[dict[str, Any]],
    sources: dict[str, str],
    existing_skills: list[dict[str, Any]],
) -> tuple[list[Proposal], list[dict[str, str]]]:
    """(kept, dropped with reasons). `sources` maps source ids to their full text."""
    have: set[tuple[str, ...]] = set()
    for data in existing_skills:
        have |= identity_keys(Section.SKILL, data)
    normalized_sources = {k: _norm(v) for k, v in sources.items()}
    kept: list[Proposal] = []
    dropped: list[dict[str, str]] = []
    for raw in proposals[:MAX_PROPOSALS]:
        name = str(raw.get("name") or "").strip()
        quote = str(raw.get("quote") or "").strip()
        source_id = str(raw.get("source_id") or "")
        category = str(raw.get("category") or "").strip() or None

        def drop(reason: str, name: str = name) -> None:
            dropped.append({"name": name[:120], "reason": reason})

        if not is_plausible_skill(name):
            drop("doesn't look like a skill name")
            continue
        text = normalized_sources.get(source_id)
        if text is None:
            drop("cites a source that isn't yours")
            continue
        if not quote or _norm(quote) not in text:
            drop("its quote isn't in the cited text")
            continue
        if _norm(name) not in _norm(quote):
            drop("the quote doesn't mention it")
            continue
        keys = identity_keys(Section.SKILL, {"name": name})
        if keys & have:
            drop("you already have it")
            continue
        have |= keys
        kept.append(Proposal(name, category[:120] if category else None, quote[:600], source_id))
    return kept, dropped
