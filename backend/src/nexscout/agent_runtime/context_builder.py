"""Task-specific context construction within a model's token budget (spec §10).

Each model call gets only what its task needs, assembled from prioritized sections:
required sections must fit (else `ContextOverflow`, and the caller splits the task or reduces
scope); optional sections are added by priority and trimmed item by item. Compaction must
preserve every id it was given, so evidence references can never be silently lost.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

CHARS_PER_TOKEN = 3.5  # conservative heuristic for mixed English/JSON across tokenizers
SAFETY_MARGIN = 0.10


def estimate_tokens(text: str) -> int:
    """Provider-neutral estimate. Over-estimates slightly on purpose (safety margin)."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


class ContextOverflow(Exception):
    """Required context does not fit the model's budget."""


@dataclass
class Section:
    name: str
    items: Sequence[str]  # already rendered lines/blocks; trimmed from the end when optional
    required: bool = False
    priority: int = 100  # lower = more important
    header: str | None = None


@dataclass
class BuiltContext:
    text: str
    included: dict[str, int] = field(default_factory=dict)  # section -> items included
    dropped: dict[str, int] = field(default_factory=dict)  # section -> items dropped
    tokens: int = 0
    budget: int = 0


def input_budget(context_window: int, max_output_tokens: int, reserved: int = 0) -> int:
    usable = context_window - max_output_tokens - reserved
    return max(0, int(usable * (1 - SAFETY_MARGIN)))


def build_context(
    sections: list[Section], budget_tokens: int, fixed_overhead: str = ""
) -> BuiltContext:
    used = estimate_tokens(fixed_overhead) if fixed_overhead else 0
    out = BuiltContext(text="", budget=budget_tokens)
    parts: list[tuple[int, str]] = []
    ordered = sorted(enumerate(sections), key=lambda p: (not p[1].required, p[1].priority, p[0]))
    for original_index, sec in ordered:
        header = f"## {sec.header or sec.name}\n"
        head_cost = estimate_tokens(header)
        kept: list[str] = []
        if sec.required:
            body = "\n".join(sec.items)
            cost = head_cost + estimate_tokens(body)
            if used + cost > budget_tokens:
                raise ContextOverflow(
                    f"Required context “{sec.name}” needs about {cost} tokens; "
                    f"only {max(0, budget_tokens - used)} remain."
                )
            kept = list(sec.items)
            used += cost
        else:
            if used + head_cost >= budget_tokens:
                out.dropped[sec.name] = len(sec.items)
                continue
            used += head_cost
            for item in sec.items:
                cost = estimate_tokens(item) + 1
                if used + cost > budget_tokens:
                    break
                kept.append(item)
                used += cost
            if not kept:
                used -= head_cost
        out.included[sec.name] = len(kept)
        if len(kept) < len(sec.items):
            out.dropped[sec.name] = len(sec.items) - len(kept)
        if kept:
            parts.append((original_index, header + "\n".join(kept)))
    out.text = "\n\n".join(p for _, p in sorted(parts))
    out.tokens = used
    return out


# ------------------------------------------------------------------------------ compaction
_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


@dataclass
class CompactSummary:
    summary: str
    ids: list[str]
    decisions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)


class CompactionLostIds(Exception):
    pass


async def compact(
    items: list[str],
    summarize: Callable[[list[str]], Awaitable[CompactSummary]],
) -> CompactSummary:
    """Summarize older working memory. The result must reference every id (fact, evidence,
    approval) present in the input; otherwise the compaction is rejected."""
    required = set(_ID.findall("\n".join(items)))
    result = await summarize(items)
    missing = required - set(result.ids) - set(_ID.findall(result.summary))
    if missing:
        raise CompactionLostIds(f"Compaction dropped {len(missing)} referenced id(s).")
    return result


def render_json_lines(rows: list[dict[str, Any]]) -> list[str]:
    return [json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows]
