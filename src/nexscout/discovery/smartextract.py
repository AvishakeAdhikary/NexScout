"""SmartExtract engine — AI-driven scraping (§8.3 of plan.md).

This module implements the prompt-side and pure-Python helpers:

* :func:`extract_json` — robust LLM-JSON extraction.
* Verbatim **judge**, **strategy**, **selector** prompts (constants).
* :func:`run_judge`, :func:`run_strategy`, :func:`run_selectors` — call the
  router with the verbatim prompts above.
* :func:`execute_json_ld`, :func:`execute_api_response`,
  :func:`execute_css_selectors` — phase-3 executors.

The browser-side intelligence collector (Phase 1) requires Selenium and is
stubbed via :class:`PageBriefing`; the real CDP-driven implementation lands
alongside the apply/browser pool in M7.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verbatim prompts (§8.3)
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """You are filtering intercepted API responses from a job listings website.
Decide if this API response contains actual job listing data
(titles, companies, locations, etc).

API Response Summary:
  URL: {url}
  Status: {status}
  Size: {size} chars
  Type: {type}
  Keys/Fields: {fields}
  Sample: {sample}

Is this job listing data? Answer in under 10 words. Return ONLY valid JSON:
{{"relevant": true, "reason": "job objects with title/company"}}
or
{{"relevant": false, "reason": "auth endpoint"}}

No explanation, no markdown, no thinking."""


STRATEGY_PROMPT = """You are analyzing a job listings page to pick the best extraction strategy.

Below is a lightweight intelligence briefing — JSON-LD data, intercepted API
responses, data-testid attributes, and DOM statistics. NO raw DOM HTML.

Pick the BEST strategy:

1. "json_ld" — ONLY if briefing shows JobPosting JSON-LD entries (it will say "usable!")
2. "api_response" — ONLY if an intercepted API response has job-like fields
   (name, title, salary, description, location, slug)
3. "css_selectors" — when neither JSON-LD nor API data has job data

HOW TO THINK:
- If the briefing says "JSON-LD: NO JobPosting entries", do NOT pick json_ld.
- For api_response: "url_pattern" must be a substring matching one of the
  INTERCEPTED API URLs listed above (not the page URL!). Copy a unique part.
- For api_response: "items_path" must point to the ARRAY of items.
  Use dot notation with [n] only for traversing into a specific index to reach
  an inner array. E.g. items_path "results[0].hits" when data is
  {{"results":[{{"hits":[…]}}]}}.
- For api_response: field paths (title, salary, etc.) are relative to each item.
  If items are like {{"_source":{{"Title":"…"}}}}, use "_source.Title".
- For css_selectors: just return
  {{"strategy":"css_selectors","reasoning":"...","extraction":{{}}}} —
  selectors will be generated separately.

Return ONLY valid JSON.

For json_ld:
{{"strategy":"json_ld","reasoning":"...","extraction":{{
  "title":"title","salary":"baseSalary_path_or_null",
  "description":"description","location":"jobLocation[0].address.addressCountry",
  "url":"url_field"}}}}

For api_response:
{{"strategy":"api_response","reasoning":"...","extraction":{{
  "url_pattern":"actual.url.substring","items_path":"path.to.array",
  "title":"...","salary":"...","description":"...","location":"...","url":"..."}}}}

For css_selectors:
{{"strategy":"css_selectors","reasoning":"...","extraction":{{}}}}

Keep reasoning under 20 words. No markdown, no code fences.

INTELLIGENCE BRIEFING:
{briefing}"""


SELECTOR_PROMPT = """You are a senior web scraping engineer. Below is the cleaned HTML of a job
listings page.

Your task:
1. Find the repeating HTML elements that represent individual job listings.
2. Generate CSS selectors to extract data from them.

Return JSON with:
- "job_card": CSS selector matching each job card (must match ALL cards)
- "title": selector RELATIVE to the card for the job title
- "salary": selector relative to card for salary, or null
- "description": selector relative to card for description snippet, or null
- "location": selector relative to card for location, or null
- "url": selector relative to card for the <a> tag

Selector rules:
- SIMPLEST wins. [data-testid="job-card"] > li > div > [data-testid="job-card"].
- For data-testid/data-id with DYNAMIC values (data-testid="card-123") use
  prefix: [data-testid^="card-"].
- For STATIC values use exact: [data-testid="job-card"].
- Prefer semantic HTML (article, section, h2/h3) over div.
- NEVER use hashed/generated classes: sc-*, css-*, random 5-8 char strings.
- Max 2 levels deep; one level is best.
- The "url" selector should target an <a>; we extract its href.
- If the page has NO job listings visible, return {"error":"no job listings found"}.

Return ONLY valid JSON, no explanation, no markdown.

PAGE HTML:
{page_html}"""


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text or "")


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _balanced_object(text: str) -> str | None:
    """Return the outermost balanced ``{...}`` block in ``text`` (or None)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    return text[start : end + 1]


def extract_json(text: str) -> Any:
    """Robustly parse LLM JSON output.

    Strips ``<think>`` blocks, ```` ```json ``` ```` fences, locates the
    outermost balanced ``{...}`` block, and retries by trimming trailing
    characters until ``json.loads`` succeeds. Returns ``None`` on failure.
    """
    if not text:
        return None
    cleaned = _strip_fences(_strip_think(text))
    candidate = _balanced_object(cleaned)
    if candidate is None:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return None
    # Retry by trimming up to 200 trailing chars (handles trailing junk).
    for trim in range(0, min(200, len(candidate))):
        snippet = candidate[: len(candidate) - trim] if trim else candidate
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Page intelligence briefing (data class). Phase 1 (browser scraping) lives in
# the apply/browser package; here we only define the shape the LLM consumes.
# ---------------------------------------------------------------------------


@dataclass
class PageBriefing:
    """Lightweight intelligence summary handed to the strategy LLM."""

    url: str = ""
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    next_data: dict[str, Any] | None = None
    intercepted_apis: list[dict[str, Any]] = field(default_factory=list)
    data_testids: list[dict[str, str]] = field(default_factory=list)
    dom_stats: dict[str, int] = field(default_factory=dict)
    card_candidates: list[dict[str, Any]] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        parts.append(f"URL: {self.url}")

        if self.json_ld:
            postings = [j for j in self.json_ld if (j.get("@type") == "JobPosting")]
            if postings:
                parts.append(f"JSON-LD: usable! {len(postings)} JobPosting entries")
                parts.append(f"  example keys: {sorted(postings[0].keys())[:8]}")
            else:
                parts.append("JSON-LD: NO JobPosting entries")
        else:
            parts.append("JSON-LD: none")

        if self.intercepted_apis:
            parts.append(f"Intercepted APIs ({len(self.intercepted_apis)}):")
            for api in self.intercepted_apis[:5]:
                parts.append(
                    f"  - URL: {api.get('url')!r} "
                    f"status={api.get('status')} "
                    f"size={api.get('size')} "
                    f"fields={api.get('fields', [])[:8]}"
                )
        else:
            parts.append("Intercepted APIs: none")

        if self.data_testids:
            parts.append(f"data-testids ({len(self.data_testids)}):")
            for el in self.data_testids[:12]:
                parts.append(f"  - <{el.get('tag')}> testid={el.get('testid')!r} text={el.get('text', '')[:60]!r}")
        else:
            parts.append("data-testids: none")

        if self.dom_stats:
            parts.append(f"DOM stats: {self.dom_stats}")

        if self.card_candidates:
            parts.append("Card candidates:")
            for c in self.card_candidates[:3]:
                parts.append(
                    f"  - parent={c.get('parent_selector')!r} child={c.get('child_selector')!r} count={c.get('count')}"
                )

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Router invocations
# ---------------------------------------------------------------------------


def run_judge(
    router: LLMRouter,
    *,
    url: str,
    status: int | str,
    size: int,
    content_type: str,
    fields: list[str],
    sample: str,
    max_tokens: int = 128,
) -> dict[str, Any] | None:
    """Phase 1.5 judge — decide whether an API response is jobs data."""
    prompt = JUDGE_PROMPT.format(
        url=url,
        status=status,
        size=size,
        type=content_type,
        fields=fields,
        sample=sample[:600],
    )
    text = router.ask(
        "judge",
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    parsed = extract_json(text)
    return parsed if isinstance(parsed, dict) else None


def run_strategy(
    router: LLMRouter,
    briefing: PageBriefing,
    *,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """Phase 2 strategy LLM."""
    prompt = STRATEGY_PROMPT.format(briefing=briefing.render())
    text = router.ask(
        "discover",
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    parsed = extract_json(text)
    return parsed if isinstance(parsed, dict) else None


def run_selectors(
    router: LLMRouter,
    *,
    page_html: str,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """Phase 2 selector LLM for the ``css_selectors`` strategy."""
    cleaned = clean_page_html(page_html)
    prompt = SELECTOR_PROMPT.format(page_html=cleaned[:150_000])
    text = router.ask(
        "discover",
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    parsed = extract_json(text)
    return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Phase 3 executors
# ---------------------------------------------------------------------------

_PATH_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def resolve_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path with optional ``[n]`` indices."""
    if not path:
        return obj
    current: Any = obj
    for m in _PATH_TOKEN_RE.finditer(path):
        key, idx = m.group(1), m.group(2)
        if current is None:
            return None
        if idx is not None:
            try:
                current = current[int(idx)]
            except (IndexError, TypeError, ValueError):
                return None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


def _coerce_display(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str):
        return val.strip() or None
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        out = ", ".join(str(_coerce_display(v) or "") for v in val if v is not None)
        return out.strip(", ") or None
    if isinstance(val, dict):
        for k in ("name", "title", "value", "text"):
            if k in val:
                return _coerce_display(val[k])
        return None
    return str(val)


def execute_json_ld(json_ld_entries: list[dict[str, Any]], extraction: dict[str, str]) -> list[dict[str, Any]]:
    """Walk JSON-LD JobPosting entries and resolve field paths."""
    out: list[dict[str, Any]] = []
    for entry in json_ld_entries:
        graph = entry.get("@graph")
        nodes: list[dict[str, Any]] = graph if isinstance(graph, list) else [entry]
        for node in nodes:
            if not isinstance(node, dict) or node.get("@type") != "JobPosting":
                continue
            out.append(
                {
                    "title": _coerce_display(resolve_path(node, extraction.get("title", "title"))),
                    "salary": _coerce_display(resolve_path(node, extraction.get("salary") or "")),
                    "description": _coerce_display(resolve_path(node, extraction.get("description", "description"))),
                    "location": _coerce_display(resolve_path(node, extraction.get("location") or "")),
                    "url": _coerce_display(resolve_path(node, extraction.get("url", "url"))),
                }
            )
    return out


def execute_api_response(responses: list[dict[str, Any]], extraction: dict[str, str]) -> list[dict[str, Any]]:
    """Find an intercepted response by ``url_pattern`` and walk ``items_path``."""
    pattern = extraction.get("url_pattern", "")
    target = next((r for r in responses if pattern and pattern in str(r.get("url", ""))), None)
    if target is None:
        return []
    items = resolve_path(target.get("body"), extraction.get("items_path", ""))
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            {
                "title": _coerce_display(resolve_path(item, extraction.get("title", "title"))),
                "salary": _coerce_display(resolve_path(item, extraction.get("salary") or "")),
                "description": _coerce_display(resolve_path(item, extraction.get("description") or "")),
                "location": _coerce_display(resolve_path(item, extraction.get("location") or "")),
                "url": _coerce_display(resolve_path(item, extraction.get("url", "url"))),
            }
        )
    return out


_UTILITY_CLASS_RE = re.compile(
    r"^([a-z]{1,2}-\d+|col-\d+|d-\w+|mx-\d+|my-\d+|px-\d+|py-\d+|"
    r"text-\w+|bg-\w+|flex-\w+|grid-\w+|css-[a-z0-9]+|sc-[a-zA-Z0-9-]+|"
    r"[a-zA-Z]{5,8})$"
)


def clean_page_html(html: str) -> str:
    """Strip layout-only classes and noisy elements from a page snapshot."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "svg", "noscript", "iframe", "link", "meta", "head", "footer", "nav"]):
        tag.decompose()
    for el in soup.find_all(True):
        classes = el.get("class")
        if isinstance(classes, list):
            kept = [c for c in classes if not _UTILITY_CLASS_RE.match(c)]
            if kept:
                el["class"] = kept
            else:
                del el["class"]
    return str(soup)


def execute_css_selectors(html: str, selectors: dict[str, Any], base_url: str = "") -> list[dict[str, Any]]:
    """Apply LLM-generated CSS selectors to a page snapshot."""
    if "error" in selectors:
        return []
    soup = BeautifulSoup(html or "", "lxml")
    card_sel = selectors.get("job_card") or ""
    if not card_sel:
        return []
    cards = soup.select(card_sel)
    out: list[dict[str, Any]] = []
    for card in cards:

        def pick(field_name: str) -> str | None:
            sel = selectors.get(field_name)
            if not sel:
                return None
            el = card.select_one(sel)  # noqa: B023 - intentional closure on `card`
            if el is None:
                return None
            return el.get_text(" ", strip=True) or None

        url_sel = selectors.get("url")
        url_val: str | None = None
        if url_sel:
            el = card.select_one(url_sel)
            if el is not None:
                href = el.get("href") if hasattr(el, "get") else None
                if href:
                    url_val = str(href)
                    if base_url and url_val.startswith("/"):
                        url_val = base_url.rstrip("/") + url_val
        out.append(
            {
                "title": pick("title"),
                "salary": pick("salary"),
                "description": pick("description"),
                "location": pick("location"),
                "url": url_val,
            }
        )
    return out
