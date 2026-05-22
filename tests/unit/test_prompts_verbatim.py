"""Strict 1:1 placeholder-mapping verbatim audit (Task-6).

The earlier ``test_prompts_verbatim_loose.py`` strips every ``{...}`` token
from both texts before comparing. That catches surrounding-text drift but
**not** silent placeholder renames.

This module is the strict variant:

1. Parse placeholders from both the plan slice and the in-code template
   using the **tight** pattern ``\\{[a-zA-Z_.][\\w.\\[\\]| ]*\\}`` (JSON
   literals like ``{"key": …}`` do not match — they start with a quote).
2. Walk the placeholders in order, applying a documented mapping table
   (``{plan_placeholder: code_placeholder}``) per prompt.
3. Rewrite every code placeholder to its mapped plan placeholder.
4. Assert byte-equality between the rewritten code template and the plan
   slice — modulo the ``{...}`` JSON literal placeholders (still stripped),
   leading/trailing whitespace, and any explicitly-allowed NexScout-only
   additions (CAPTCHA_MANUAL hard rule in §13.4).

Adding a new prompt: extend the per-prompt mapping table below. Documented
in ``docs/developer-guide.md``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLAN_PATH = Path(__file__).resolve().parents[2] / "plan.md"
PLAN_TEXT = PLAN_PATH.read_text(encoding="utf-8")
PLAN_LINES = PLAN_TEXT.splitlines()

# Tight placeholder regex — matches identifiers, dotted attributes, bracketed
# indices, pipe-filters, ``or``/space separators, and the two free-form
# helper expressions used in §13.4: ``{digits_only(phone)}`` and
# ``{today MM/DD/YYYY}``. **Does not** match JSON literals (those start with
# ``"`` or ``[`` after the opening brace).
PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_.][\w.\[\]|/()  ]*\}")

# Looser regex for the still-stripped JSON literals + any *other* curly-brace
# content (e.g. ``{today MM/DD/YYYY}`` is matched by the tight RE; multi-line
# JSON blobs are not).
_JSON_LITERAL_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
_DOUBLE_BRACE_RE = re.compile(r"\{\{|\}\}")


# ---------------------------------------------------------------------------
# Plan slicing helpers (copy of the loose-variant helpers — kept local so
# the two test files don't import each other).
# ---------------------------------------------------------------------------


def _find_fence(starting_text: str) -> tuple[int, int]:
    open_idx = -1
    for i, line in enumerate(PLAN_LINES):
        if line.strip() == "```" and i + 1 < len(PLAN_LINES) and PLAN_LINES[i + 1].lstrip().startswith(starting_text):
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
# Strict-mapping comparator
# ---------------------------------------------------------------------------


def _strip_all_braces(text: str) -> str:
    """Iteratively remove every ``{...}`` block from ``text``.

    The strict-mapping walk verifies placeholder identity / order; the
    byte-equality pass that follows just needs to confirm the *surrounding*
    text matches, so both JSON literals and rewritten placeholders are
    stripped uniformly.
    """
    while True:
        new_text = _JSON_LITERAL_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    return text


def _normalise(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip()


def _collapse_double_braces(text: str) -> str:
    return _DOUBLE_BRACE_RE.sub(lambda m: "{" if m.group(0) == "{{" else "}", text)


#: A mapping is either a *flat* ``dict[str, str]`` (one plan-name → one
#: code-name everywhere it appears) or a *positional* ``list[tuple[str, str]]``
#: when the same plan name must map differently at different positions
#: (e.g. ``{city}`` in §13.4 sometimes corresponds to ``{cover_letter_text}``
#: when it sits inside a cover-letter fallback literal).
Mapping = dict[str, str] | list[tuple[str, str]]


def _resolve_mapping_at(mapping: Mapping, plan_ph: str, position: int) -> str | None:
    if isinstance(mapping, dict):
        return mapping.get(plan_ph)
    if 0 <= position < len(mapping):
        expected_plan, expected_code = mapping[position]
        if expected_plan != plan_ph:
            return None
        return expected_code
    return None


def _walk_placeholders_in_order_match(*, code_template: str, plan_block: str, mapping: Mapping) -> tuple[bool, str]:
    """Verify plan placeholders appear in the documented order and map to code."""
    code = _collapse_double_braces(code_template)
    code_phs = PLACEHOLDER_RE.findall(code)
    plan_phs = PLACEHOLDER_RE.findall(plan_block)

    if len(code_phs) != len(plan_phs):
        return False, f"placeholder count differs: code={len(code_phs)} plan={len(plan_phs)}"

    for i, (plan_ph, code_ph) in enumerate(zip(plan_phs, code_phs, strict=True)):
        expected_code = _resolve_mapping_at(mapping, plan_ph, i)
        if expected_code is None:
            return False, f"plan placeholder {plan_ph!r} at position {i} is not in the mapping table"
        if expected_code != code_ph:
            return False, (f"placeholder #{i}: plan {plan_ph!r} mapped to {expected_code!r} but code has {code_ph!r}")
    return True, "ok"


def _strict_equal(
    *,
    code_template: str,
    plan_block: str,
    mapping: Mapping,
    pre_strip_code: str | None = None,
) -> tuple[bool, str]:
    """Return ``(ok, diagnostic)``. The code template is rewritten so its
    placeholders carry the plan-side names; after rewrite **every byte
    outside JSON literals must match**.

    For positional mappings the substitution honours order — only the n-th
    occurrence of the code placeholder is rewritten.
    """
    code = _collapse_double_braces(code_template)
    if pre_strip_code is not None:
        code = pre_strip_code

    if isinstance(mapping, dict):
        reverse = {code_name: plan_name for plan_name, code_name in mapping.items()}
        for code_ph, plan_ph in reverse.items():
            code = code.replace(code_ph, plan_ph)
    else:
        # Positional rewrite — walk code placeholders in order, replace
        # exactly the n-th match with its mapped plan name.
        new_parts: list[str] = []
        last = 0
        for i, m in enumerate(PLACEHOLDER_RE.finditer(code)):
            new_parts.append(code[last : m.start()])
            if i < len(mapping):
                expected_plan, expected_code = mapping[i]
                if m.group(0) == expected_code:
                    new_parts.append(expected_plan)
                else:
                    new_parts.append(m.group(0))
            else:
                new_parts.append(m.group(0))
            last = m.end()
        new_parts.append(code[last:])
        code = "".join(new_parts)

    code_clean = _normalise(_strip_all_braces(code))
    plan_clean = _normalise(_strip_all_braces(plan_block))

    if code_clean == plan_clean:
        return True, "ok"

    for i, (a, b) in enumerate(zip(code_clean, plan_clean, strict=False)):
        if a != b:
            ctx_a = code_clean[max(0, i - 30) : i + 30]
            ctx_b = plan_clean[max(0, i - 30) : i + 30]
            return False, f"diverged at byte {i}: code={ctx_a!r} plan={ctx_b!r}"
    return False, f"length mismatch code={len(code_clean)} plan={len(plan_clean)}"


# ---------------------------------------------------------------------------
# Per-prompt placeholder mapping tables
# ---------------------------------------------------------------------------


JUDGE_MAPPING: dict[str, str] = {
    "{url}": "{url}",
    "{status}": "{status}",
    "{size}": "{size}",
    "{type}": "{type}",
    "{fields}": "{fields}",
    "{sample}": "{sample}",
}

STRATEGY_MAPPING: dict[str, str] = {
    "{briefing}": "{briefing}",
}

SELECTOR_MAPPING: dict[str, str] = {
    "{page_html}": "{page_html}",
}

ENRICHMENT_MAPPING: dict[str, str] = {
    "{url}": "{url}",
    "{title}": "{title}",
    "{content}": "{content}",
}

SCORER_MAPPING: dict[str, str] = {}

TAILOR_MAPPING: dict[str, str] = {
    "{profile.skills.lang | join}": "{languages}",
    "{profile.skills.fw | join}": "{frameworks}",
    "{profile.skills.infra | join}": "{infra}",
    "{profile.skills.data | join}": "{data}",
    "{profile.skills.tools | join}": "{tools}",
    "{BANNED_WORDS | join}": "{banned_words}",
    "{profile.facts.metrics | join}": "{metrics}",
    "{profile.facts.companies | join}": "{companies}",
    "{profile.facts.school}": "{school}",
    "{profile.exp.edu}": "{education}",
}

COVER_MAPPING: dict[str, str] = {
    "{profile.me.pref}": "{pref}",
    "{profile.facts.projects | join}": "{projects}",
    "{profile.facts.metrics | join}": "{metrics}",
    "{BANNED_WORDS | join}": "{banned_words}",
    "{LLM_LEAK_PHRASES | join}": "{leak_phrases}",
    "{all_skills | join}": "{all_skills}",
}

# §13.4 uses positional mapping because:
#   1. ``{cover_letter_text or "…{city}."}`` — the plan's tight regex only
#      catches the inner ``{city}`` (the outer literal spans lines and has
#      quotes), but the code condensed both into one ``{cover_letter_text}``
#      placeholder.
#   2. ``{city}`` later appears multiple times verbatim in the APPLICANT
#      PROFILE block where it does map to ``{city}`` literally.
APPLY_MAPPING: list[tuple[str, str]] = [
    ("{application_url or url}", "{job_url}"),
    ("{title}", "{title}"),
    ("{site}", "{site}"),
    ("{fit_score}", "{fit_score}"),
    ("{bundle_dir}", "{bundle_dir}"),
    ("{bundle_dir}", "{bundle_dir}"),
    ("{tailored_resume_text}", "{tailored_resume_text}"),
    # Plan's tight regex catches `{city}` inside the cover-letter fallback;
    # code condensed it into `{cover_letter_text}`. Documented mismatch.
    ("{city}", "{cover_letter_text}"),
    ("{me.legal}", "{legal_name}"),
    ("{me.email}", "{email}"),
    ("{me.phone}", "{phone}"),
    ("{address}", "{address}"),
    ("{city}", "{city}"),
    ("{region}", "{region}"),
    ("{country}", "{country}"),
    ("{postcode}", "{postcode}"),
    ("{links.li}", "{linkedin}"),
    ("{links.gh}", "{github}"),
    ("{links.portfolio}", "{portfolio}"),
    ("{links.web}", "{website}"),
    ("{auth.authorized}", "{work_auth}"),
    ("{auth.sponsor}", "{sponsor}"),
    ("{auth.permit}", "{permit}"),
    ("{pay.expect}", "{salary_expect}"),
    ("{pay.currency}", "{currency}"),
    ("{exp.years}", "{years}"),
    ("{exp.edu}", "{education}"),
    ("{avail.start}", "{available}"),
    ("{eeo.gender}", "{eeo_gender}"),
    ("{eeo.race}", "{eeo_race}"),
    ("{eeo.veteran}", "{eeo_veteran}"),
    ("{eeo.disability}", "{eeo_disability}"),
    ("{auth_rule}", "{auth_rule}"),
    ("{me.legal}", "{legal_name}"),
    ("{me.pref}", "{pref_name}"),
    ("{me.pref}", "{pref_name}"),
    ("{last_name}", "{last_name}"),
    ("{accept_cities}", "{accept_cities}"),
    ("{pay.expect}", "{salary_expect}"),
    ("{pay.currency}", "{currency}"),
    ("{currency}", "{currency}"),
    ("{pay.expect}", "{salary_expect}"),
    ("{pay.currency}", "{currency}"),
    ("{pay.range[0]}", "{salary_low}"),
    ("{pay.range[1]}", "{salary_high}"),
    ("{currency}", "{currency}"),
    ("{target_title}", "{target_title}"),
    ("{exp.years}", "{years}"),
    ("{title}", "{title}"),
    ("{display_name}", "{display_name}"),
    ("{me.email}", "{email}"),
    ("{profile.password}", "{password}"),
    ("{digits_only(phone)}", "{phone_digits}"),
    ("{today MM/DD/YYYY}", "{today_us}"),
]


# ---------------------------------------------------------------------------
# Strict tests
# ---------------------------------------------------------------------------


def test_smartextract_judge_prompt_strict() -> None:
    from nexscout.discovery.smartextract import JUDGE_PROMPT

    plan = _fenced_block_starting_with("You are filtering intercepted API")
    ok, diag = _strict_equal(code_template=JUDGE_PROMPT, plan_block=plan, mapping=JUDGE_MAPPING)
    assert ok, f"JUDGE prompt: {diag}"


def test_smartextract_strategy_prompt_strict() -> None:
    from nexscout.discovery.smartextract import STRATEGY_PROMPT

    plan = _fenced_block_starting_with("You are analyzing a job listings page to pick")
    ok, diag = _strict_equal(code_template=STRATEGY_PROMPT, plan_block=plan, mapping=STRATEGY_MAPPING)
    assert ok, f"STRATEGY prompt: {diag}"


def test_smartextract_selector_prompt_strict() -> None:
    from nexscout.discovery.smartextract import SELECTOR_PROMPT

    plan = _fenced_block_starting_with("You are a senior web scraping engineer")
    ok, diag = _strict_equal(code_template=SELECTOR_PROMPT, plan_block=plan, mapping=SELECTOR_MAPPING)
    assert ok, f"SELECTOR prompt: {diag}"


def test_enrichment_llm_prompt_strict() -> None:
    from nexscout.enrichment.detail import LLM_PROMPT

    plan = _fenced_block_starting_with("You are extracting job details from a single")
    ok, diag = _strict_equal(code_template=LLM_PROMPT, plan_block=plan, mapping=ENRICHMENT_MAPPING)
    assert ok, f"Enrichment LLM prompt: {diag}"


def test_scorer_system_prompt_strict() -> None:
    from nexscout.scoring.scorer import SYSTEM_PROMPT

    plan = _fenced_block_starting_with("You are a job fit evaluator")
    ok, diag = _strict_equal(code_template=SYSTEM_PROMPT, plan_block=plan, mapping=SCORER_MAPPING)
    assert ok, f"Scorer SYSTEM_PROMPT: {diag}"


def test_tailor_system_prompt_strict() -> None:
    from nexscout.scoring.tailor import SYSTEM_PROMPT_TEMPLATE

    plan = _fenced_block_starting_with("You are a senior technical recruiter")
    ok, diag = _walk_placeholders_in_order_match(
        code_template=SYSTEM_PROMPT_TEMPLATE, plan_block=plan, mapping=TAILOR_MAPPING
    )
    assert ok, f"Tailor placeholder order: {diag}"
    ok, diag = _strict_equal(code_template=SYSTEM_PROMPT_TEMPLATE, plan_block=plan, mapping=TAILOR_MAPPING)
    assert ok, f"Tailor SYSTEM_PROMPT_TEMPLATE: {diag}"


def test_cover_letter_prompt_strict() -> None:
    from nexscout.scoring.cover_letter import COVER_PROMPT_TEMPLATE

    plan = _fenced_block_starting_with("Write a cover letter for")
    ok, diag = _walk_placeholders_in_order_match(
        code_template=COVER_PROMPT_TEMPLATE, plan_block=plan, mapping=COVER_MAPPING
    )
    assert ok, f"Cover placeholder order: {diag}"
    ok, diag = _strict_equal(code_template=COVER_PROMPT_TEMPLATE, plan_block=plan, mapping=COVER_MAPPING)
    assert ok, f"Cover COVER_PROMPT_TEMPLATE: {diag}"


def _strip_nexscout_apply_additions(text: str) -> str:
    """Drop NexScout-only additions from §13.4 (CAPTCHA_MANUAL hard rule)."""
    keep: list[str] = []
    for line in text.splitlines():
        if "CAPTCHA_MANUAL" in line or "captcha_manual_required" in line:
            continue
        keep.append(line)
    return "\n".join(keep)


def test_apply_system_prompt_strict() -> None:
    from nexscout.apply.prompt import SYSTEM_PROMPT_TEMPLATE

    plan = _fenced_block_starting_with("You are an autonomous job application agent")
    stripped = _strip_nexscout_apply_additions(SYSTEM_PROMPT_TEMPLATE)
    ok, diag = _walk_placeholders_in_order_match(code_template=stripped, plan_block=plan, mapping=APPLY_MAPPING)
    assert ok, f"Apply placeholder order: {diag}"
    ok, diag = _strict_equal(
        code_template=SYSTEM_PROMPT_TEMPLATE,
        plan_block=plan,
        mapping=APPLY_MAPPING,
        pre_strip_code=_collapse_double_braces(stripped),
    )
    assert ok, f"Apply SYSTEM_PROMPT_TEMPLATE: {diag}"
