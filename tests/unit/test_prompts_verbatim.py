"""Verbatim audit of the six §-pinned prompts against plan.md.

Approach: read the relevant fenced block from plan.md, strip any `{...}`
placeholder so we don't have to chase Jinja-vs-Python notation differences,
and assert the non-placeholder text matches the in-code constant the same
way. "Verbatim" therefore means *every byte outside a `{}` placeholder is
identical*; the placeholders themselves can differ in spelling because both
the plan and the code use them only as named substitution points.

Tests covered:

* §8.3  — SmartExtract  judge  (lines 597-616)
* §8.3  — SmartExtract  strategy  (lines 622-669)
* §8.3  — SmartExtract  selector  (lines 677-708)
* §9    — Enrichment    Tier 3  (lines 781-807)
* §10   — Scorer  (lines 829-851)
* §11   — Tailor system prompt  (lines 882-942)
* §12.2 — Cover letter  (lines 1063-1102)
* §13.4 — Apply agent system prompt  (lines 1228-1408)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLAN_PATH = Path(__file__).resolve().parents[2] / "plan.md"
PLAN_TEXT = PLAN_PATH.read_text(encoding="utf-8")
PLAN_LINES = PLAN_TEXT.splitlines()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
_DOUBLE_BRACE_RE = re.compile(r"\{\{|\}\}")


def _strip_placeholders(text: str, *, collapse_doubles: bool = False) -> str:
    """Normalise away every `{...}` substitution token.

    Drops trailing whitespace per line and the final trailing newline so the
    plan and the code-string compare cleanly.

    ``collapse_doubles`` should be True for *code* templates that use Python
    `str.format` escape doubling (`{{` / `}}`); the plan never doubles, so it
    must be False for plan slices.
    """
    if collapse_doubles:
        text = _DOUBLE_BRACE_RE.sub(lambda m: "{" if m.group(0) == "{{" else "}", text)
    # Iteratively erase every innermost `{...}` placeholder until none remain.
    # This handles nested JSON literals like `{"_source":{"Title":"…"}}`
    # uniformly in both plan and code, by stripping the inner brace pair first
    # and the outer pair on the next iteration.
    while True:
        new_text = _PLACEHOLDER_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip()


def _equal(code_template: str, plan_block: str) -> bool:
    return _strip_placeholders(code_template, collapse_doubles=True) == _strip_placeholders(plan_block)


def _slice_fenced_block(start_line: int, end_line: int) -> str:
    """Return the text inside a fenced block.

    `start_line` is the line number of the opening ```` ``` ```` (1-indexed).
    `end_line` is the line number of the closing fence. Returns the content
    *between* them.
    """
    return "\n".join(PLAN_LINES[start_line:end_line - 1])


def _find_fence(starting_text: str) -> tuple[int, int]:
    """Locate the fenced code block whose first non-fence line starts with
    `starting_text` and return (open_fence_lineno_0idx, close_fence_lineno_0idx).
    """
    open_idx = -1
    for i, line in enumerate(PLAN_LINES):
        if (
            line.strip() == "```"
            and i + 1 < len(PLAN_LINES)
            and PLAN_LINES[i + 1].lstrip().startswith(starting_text)
        ):
            open_idx = i
            break
    if open_idx < 0:
        pytest.fail(f"could not find fenced block starting with {starting_text!r}")
    for j in range(open_idx + 1, len(PLAN_LINES)):
        if PLAN_LINES[j].strip() == "```":
            return open_idx, j
    pytest.fail("unterminated fenced block")
    raise AssertionError("unreachable")  # pragma: no cover


def _fenced_block_starting_with(starting_text: str) -> str:
    open_idx, close_idx = _find_fence(starting_text)
    return "\n".join(PLAN_LINES[open_idx + 1 : close_idx])


# ---------------------------------------------------------------------------
# §8.3 SmartExtract prompts
# ---------------------------------------------------------------------------


def test_smartextract_judge_prompt_verbatim() -> None:
    from nexscout.discovery.smartextract import JUDGE_PROMPT

    plan_block = _fenced_block_starting_with("You are filtering intercepted API")
    assert _equal(JUDGE_PROMPT, plan_block), "SmartExtract JUDGE prompt drifted from §8.3"


def test_smartextract_strategy_prompt_verbatim() -> None:
    from nexscout.discovery.smartextract import STRATEGY_PROMPT

    plan_block = _fenced_block_starting_with("You are analyzing a job listings page to pick")
    assert _equal(STRATEGY_PROMPT, plan_block), "SmartExtract STRATEGY prompt drifted from §8.3"


def test_smartextract_selector_prompt_verbatim() -> None:
    from nexscout.discovery.smartextract import SELECTOR_PROMPT

    plan_block = _fenced_block_starting_with("You are a senior web scraping engineer")
    assert _equal(SELECTOR_PROMPT, plan_block), "SmartExtract SELECTOR prompt drifted from §8.3"


# ---------------------------------------------------------------------------
# §9 Enrichment Tier 3 prompt
# ---------------------------------------------------------------------------


def test_enrichment_llm_prompt_verbatim() -> None:
    from nexscout.enrichment.detail import LLM_PROMPT

    plan_block = _fenced_block_starting_with("You are extracting job details from a single")
    assert _equal(LLM_PROMPT, plan_block), "Enrichment Tier 3 LLM prompt drifted from §9"


# ---------------------------------------------------------------------------
# §10 Scorer
# ---------------------------------------------------------------------------


def test_scorer_system_prompt_verbatim() -> None:
    from nexscout.scoring.scorer import SYSTEM_PROMPT

    plan_block = _fenced_block_starting_with("You are a job fit evaluator")
    assert _equal(SYSTEM_PROMPT, plan_block), "Scorer SYSTEM_PROMPT drifted from §10"


# ---------------------------------------------------------------------------
# §11 Tailor
# ---------------------------------------------------------------------------


def test_tailor_system_prompt_verbatim() -> None:
    from nexscout.scoring.tailor import SYSTEM_PROMPT_TEMPLATE

    plan_block = _fenced_block_starting_with("You are a senior technical recruiter")
    assert _equal(SYSTEM_PROMPT_TEMPLATE, plan_block), "Tailor SYSTEM_PROMPT_TEMPLATE drifted from §11"


# ---------------------------------------------------------------------------
# §12.2 Cover letter
# ---------------------------------------------------------------------------


def test_cover_letter_prompt_verbatim() -> None:
    from nexscout.scoring.cover_letter import COVER_PROMPT_TEMPLATE

    plan_block = _fenced_block_starting_with("Write a cover letter for")
    assert _equal(COVER_PROMPT_TEMPLATE, plan_block), "Cover-letter COVER_PROMPT_TEMPLATE drifted from §12.2"


# ---------------------------------------------------------------------------
# §13.4 Apply agent
# ---------------------------------------------------------------------------


def test_apply_system_prompt_verbatim() -> None:
    from nexscout.apply.prompt import SYSTEM_PROMPT_TEMPLATE

    plan_block = _fenced_block_starting_with("You are an autonomous job application agent")
    assert _equal(SYSTEM_PROMPT_TEMPLATE, plan_block), "Apply SYSTEM_PROMPT_TEMPLATE drifted from §13.4"
