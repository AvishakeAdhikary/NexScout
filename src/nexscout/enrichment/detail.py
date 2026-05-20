"""Enrichment — 3-tier cascade per §9 of plan.md.

For each pending row (``detail_scraped_at IS NULL`` and ``site NOT IN
{"glassdoor","google","Workopolis"}``):

* **Tier 1** parses ``<script type="application/ld+json">`` for a
  ``JobPosting`` and accepts a description >= 50 characters.
* **Tier 2** runs the verbatim ``APPLY_SELECTORS`` / ``DESCRIPTION_SELECTORS``
  arrays against the HTML and accepts a description >= 100 characters.
* **Tier 3** sends the cleaned main-content HTML to the LLM with the verbatim
  §9 prompt and parses the resulting JSON via ``extract_json``.

Persistence and per-site politeness delays are also defined here.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

import yaml
from bs4 import BeautifulSoup, Tag

from ..core.config import nexscout_dir
from ..discovery.smartextract import extract_json

if TYPE_CHECKING:
    from ..browser.driver import BrowserFactory
    from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

# Sites we never enrich — they are either content-less aggregators
# or aggressively bot-blocked (§9).
SKIP_SITES: frozenset[str] = frozenset({"glassdoor", "google", "Workopolis"})

# ---------------------------------------------------------------------------
# Verbatim §9 constants — DO NOT MODIFY
# ---------------------------------------------------------------------------

APPLY_SELECTORS: list[str] = [
    'a[href*="apply"]',
    'a[data-testid*="apply"]',
    'a[class*="apply"]',
    'a[aria-label*="pply"]',
    'button[data-testid*="apply"]',
    "a#apply_button",
    ".postings-btn-wrapper a",
    "a.ashby-job-posting-apply-button",
    '#grnhse_app a[href*="apply"]',
    'a[data-qa="btn-apply"]',
    'a[class*="btn-apply"]',
    'a[class*="apply-btn"]',
    'a[class*="apply-button"]',
]

DESCRIPTION_SELECTORS: list[str] = [
    "#job-description",
    "#job_description",
    "#jobDescriptionText",
    ".job-description",
    ".job_description",
    '[class*="job-description"]',
    '[class*="jobDescription"]',
    '[data-testid*="description"]',
    '[data-testid="job-description"]',
    ".posting-page .posting-categories + div",
    "#content .posting-page",
    "#app_body .content",
    "#grnhse_app .content",
    ".ashby-job-posting-description",
    '[class*="posting-description"]',
    '[class*="job-detail"]',
    '[class*="jobDetail"]',
    '[class*="job-content"]',
    '[class*="job-body"]',
    '[role="main"] article',
    "main article",
    'article[class*="job"]',
    ".job-posting-content",
]

# Verbatim Tier 3 LLM prompt (§9).
LLM_PROMPT = """You are extracting job details from a single job posting page.

PAGE URL: {url}
PAGE TITLE: {title}

Find TWO things in the HTML below:
1. The full job description text (responsibilities, requirements, etc.)
2. The URL of the "Apply" button/link

Rules:
- For description: extract the FULL text. Include all sections.
- For apply URL: find the href of the link/button that starts the application.
- If you cannot find one, set it to null.
- Also detect: "cover_required" — true ONLY if the page clearly asks for a
  cover letter (a dedicated field, an upload labelled "cover letter",
  or text demanding one).

Return ONLY valid JSON:
{{"full_description":"…","application_url":"https://…" or null,
 "cover_required": true|false}}

No explanation, no markdown. Keep reasoning under 20 words.

HTML:
{content}"""

# Per-site politeness delays (§9).
SITE_DELAYS: dict[str, float] = {
    "RemoteOK": 3.0,
    "WelcomeToTheJungle": 2.0,
    "Job Bank Canada": 1.5,
    "CareerJet Canada": 3.0,
    "Hacker News Jobs": 1.0,
    "BuiltIn Remote": 2.0,
}
DEFAULT_DELAY = 2.0


_PERMANENT_HTTP: frozenset[int] = frozenset({404, 410, 451})
_TRANSIENT_HTTP: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


def is_permanent_http_error(status: int) -> bool:
    """True for HTTP codes the cascade must NOT retry (404/410/451)."""
    return status in _PERMANENT_HTTP


def is_transient_http_error(status: int) -> bool:
    """True for HTTP codes the cascade should retry (408/429/5xx)."""
    return status in _TRANSIENT_HTTP


# ---------------------------------------------------------------------------
# HTML cleaning helpers
# ---------------------------------------------------------------------------


def clean_description_html(html: str) -> str:
    """Collapse a posting-description HTML blob to readable plain text.

    Per §9: ``<br>`` → ``\n``; ``<li>`` → ``- ``; paragraphs → blank line
    separated; collapse runs of 3+ newlines to ``\n\n``.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # <br> → newline
    for br in soup.find_all("br"):
        br.replace_with("\n")

    # <li> → "- text" (string node so list items survive any further parent walk).
    for li in soup.find_all("li"):
        text = li.get_text(" ", strip=True)
        li.replace_with(f"\n- {text}")

    # Block-level elements become blank-line separated paragraphs.
    parts: list[str] = []
    for p in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "ul", "ol"]):
        text = p.get_text("\n", strip=True)
        if text:
            parts.append(text)
    text = "\n\n".join(parts) if parts else soup.get_text("\n", strip=True)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------------
# JSON-LD parsing (Tier 1)
# ---------------------------------------------------------------------------


def parse_jsonld_blocks(html: str) -> list[Any]:
    """Return every parseable JSON object found in ``application/ld+json`` scripts."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[Any] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not isinstance(tag, Tag):
            continue
        raw = tag.string or tag.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites stuff multiple JSON objects in one script — try the
            # robust extractor.
            data = extract_json(raw)
            if data is None:
                continue
        out.append(data)
    return out


def _iter_jsonld_objects(blocks: list[Any]) -> list[dict[str, Any]]:
    """Walk through every dict inside the JSON-LD blocks (recursing @graph)."""
    out: list[dict[str, Any]] = []
    stack: list[Any] = list(blocks)
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            out.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
    return out


def extract_posting_from_jsonld(blocks: list[Any]) -> dict[str, Any] | None:
    """Return the first JSON-LD object whose ``@type`` is ``JobPosting``."""
    for obj in _iter_jsonld_objects(blocks):
        ty = obj.get("@type")
        if ty == "JobPosting" or (isinstance(ty, list) and "JobPosting" in ty):
            return obj
    return None


def extract_apply_url_from_posting(posting: dict[str, Any]) -> str | None:
    """Apply ``posting.directApply ? posting.url : posting.applicationContact.url ?? posting.url``."""
    direct = posting.get("directApply")
    url = posting.get("url")
    if direct:
        return url if isinstance(url, str) else None
    contact = posting.get("applicationContact")
    if isinstance(contact, dict):
        contact_url = contact.get("url")
        if isinstance(contact_url, str) and contact_url:
            return contact_url
    return url if isinstance(url, str) else None


@dataclass
class EnrichmentResult:
    """Outcome of one Tier of the cascade."""

    full_description: str = ""
    application_url: str | None = None
    cover_required: bool = False
    tier: str = ""  # "json_ld" | "css" | "llm"

    def ok(self, *, min_chars: int) -> bool:
        return len(self.full_description) >= min_chars


def tier1_jsonld(html: str) -> EnrichmentResult | None:
    """Tier 1 — accept if JSON-LD JobPosting description >= 50 chars."""
    blocks = parse_jsonld_blocks(html)
    if not blocks:
        return None
    posting = extract_posting_from_jsonld(blocks)
    if not posting:
        return None
    desc_raw = posting.get("description") or ""
    desc = clean_description_html(desc_raw) if "<" in desc_raw else desc_raw.strip()
    if len(desc) < 50:
        return None
    return EnrichmentResult(
        full_description=desc,
        application_url=extract_apply_url_from_posting(posting),
        cover_required=False,
        tier="json_ld",
    )


# ---------------------------------------------------------------------------
# Deterministic CSS (Tier 2)
# ---------------------------------------------------------------------------


def _select_first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except (ValueError, NotImplementedError):
            continue
        if not el:
            continue
        text = el.get_text("\n", strip=True)
        if text:
            return text
    return ""


def _select_first_href(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except (ValueError, NotImplementedError):
            continue
        if not el:
            continue
        href = el.get("href") if isinstance(el, Tag) else None
        if isinstance(href, str) and href:
            return href
    return None


def tier2_css(html: str) -> EnrichmentResult | None:
    """Tier 2 — accept if a deterministic-CSS description is >= 100 chars."""
    soup = BeautifulSoup(html, "html.parser")
    desc_html = ""
    for sel in DESCRIPTION_SELECTORS:
        try:
            el = soup.select_one(sel)
        except (ValueError, NotImplementedError):
            continue
        if el is None:
            continue
        candidate = clean_description_html(str(el))
        if len(candidate) >= 100:
            desc_html = candidate
            break

    if not desc_html:
        return None

    apply_href = _select_first_href(soup, APPLY_SELECTORS)
    return EnrichmentResult(
        full_description=desc_html,
        application_url=apply_href,
        cover_required=False,
        tier="css",
    )


# ---------------------------------------------------------------------------
# LLM main-content extraction (Tier 3)
# ---------------------------------------------------------------------------

_STRIP_TAGS = ("nav", "header", "footer", "script", "style", "noscript", "svg", "iframe")
_MAIN_SELECTORS = ("main", "article", '[role="main"]', "#content", ".content")


def extract_main_content(html: str) -> str:
    """Locate the main content area; fall back to body minus chrome elements."""
    soup = BeautifulSoup(html, "html.parser")
    for sel in _MAIN_SELECTORS:
        try:
            el = soup.select_one(sel)
        except (ValueError, NotImplementedError):
            continue
        if el is not None and len(el.get_text(strip=True)) > 200:
            return str(el)

    body = soup.find("body")
    if body is None:
        return str(soup)
    for tag_name in _STRIP_TAGS:
        for t in body.find_all(tag_name):
            t.decompose()
    return str(body)


def tier3_llm(
    *,
    router: LLMRouter,
    url: str,
    title: str,
    html: str,
    max_chars: int = 30_000,
) -> EnrichmentResult | None:
    """Tier 3 — ask the LLM to extract description + apply URL + cover_required."""
    content = extract_main_content(html)[:max_chars]
    prompt = LLM_PROMPT.format(url=url, title=title, content=content)
    try:
        text = router.ask("enrich", [{"role": "user", "content": prompt}], temperature=0.0)
    except Exception as e:
        log.warning("tier3 LLM call failed for %s: %s", url, e)
        return None
    data = extract_json(text)
    if not isinstance(data, dict):
        return None
    desc = data.get("full_description") or ""
    if not isinstance(desc, str):
        desc = str(desc)
    apply_url = data.get("application_url")
    if not isinstance(apply_url, str) or not apply_url:
        apply_url = None
    cover_required = bool(data.get("cover_required"))
    if not desc.strip():
        return None
    return EnrichmentResult(
        full_description=desc.strip(),
        application_url=apply_url,
        cover_required=cover_required,
        tier="llm",
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def enrich_html(
    html: str,
    *,
    url: str,
    title: str,
    router: LLMRouter | None = None,
) -> EnrichmentResult | None:
    """Run the 3-tier cascade against an HTML string. Returns the first hit."""
    if not html:
        return None
    result = tier1_jsonld(html)
    if result and result.ok(min_chars=50):
        return result
    result = tier2_css(html)
    if result and result.ok(min_chars=100):
        return result
    if router is not None:
        return tier3_llm(router=router, url=url, title=title, html=html)
    return None


# ---------------------------------------------------------------------------
# URL resolution via sites.yaml base_urls
# ---------------------------------------------------------------------------


_BASE_URL_CACHE: dict[str, str] | None = None


def _load_base_urls() -> dict[str, str]:
    global _BASE_URL_CACHE
    if _BASE_URL_CACHE is not None:
        return _BASE_URL_CACHE
    candidates = [
        nexscout_dir() / "sites.yaml",
        Path(__file__).resolve().parent.parent / "discovery" / "sites.yaml",
    ]
    for p in candidates:
        if p.exists():
            try:
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            base = data.get("base_urls") or {}
            if isinstance(base, dict):
                _BASE_URL_CACHE = {str(k): str(v) for k, v in base.items()}
                return _BASE_URL_CACHE
    _BASE_URL_CACHE = {}
    return _BASE_URL_CACHE


def resolve_relative_url(url: str, site: str | None) -> str:
    """Resolve ``url`` against the site's base URL from sites.yaml when relative."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    base = (_load_base_urls().get(site) if site else None) or ""
    if not base:
        return url
    return urljoin(base.rstrip("/") + "/", url.lstrip("/"))


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def persist_enrichment(
    conn: sqlite3.Connection,
    url: str,
    result: EnrichmentResult,
) -> None:
    """Write a successful enrichment back to the ``jobs`` row."""
    ts = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE jobs SET full_description=?, application_url=?, cover_required=?, "
        "detail_scraped_at=?, detail_error=NULL WHERE url=?",
        (
            result.full_description,
            result.application_url,
            1 if result.cover_required else 0,
            ts,
            url,
        ),
    )


def persist_enrichment_error(conn: sqlite3.Connection, url: str, error: str) -> None:
    """Record a transient or permanent enrichment failure."""
    ts = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE jobs SET detail_error=?, detail_scraped_at=? WHERE url=?",
        (error, ts, url),
    )


# ---------------------------------------------------------------------------
# Per-row driver (small public surface; the orchestrator in pipeline.py
# loops over pending rows)
# ---------------------------------------------------------------------------


def site_delay(site: str | None) -> float:
    """Politeness sleep duration between page loads for a given site."""
    return SITE_DELAYS.get(site or "", DEFAULT_DELAY)


def enrich_row(
    *,
    row: dict[str, Any],
    factory: BrowserFactory,
    router: LLMRouter | None = None,
    headless: bool = True,
) -> EnrichmentResult | None:
    """Open the URL with a browser, run the cascade, return the result.

    Tests pass a mock ``BrowserFactory`` so no real Chrome is required.
    """
    url = row.get("application_url") or row.get("url") or ""
    site = row.get("site")
    url = resolve_relative_url(url, site)
    title = row.get("title", "") or ""

    driver = factory.make(headless=headless)
    try:
        driver.get(url)
        html = driver.page_source
    finally:
        with suppress(Exception):
            driver.quit()

    result = enrich_html(html, url=url, title=title, router=router)
    time.sleep(site_delay(site))
    return result
