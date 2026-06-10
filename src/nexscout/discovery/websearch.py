"""WebSearch discovery engine (§8.4).

Provider chain (in order):

1. Tavily, 2. Brave, 3. DuckDuckGo HTML, 4. SearXNG, 5. Google CSE — these all
hit JSON APIs and need an API key (or are public HTML scrapes).
6. **Browser fallback** — when every API provider above returns empty or is
   unconfigured, we drive an undetected Chrome at Google + DuckDuckGo and
   scrape the result links. Honours the same daily query cap.

After scraping we de-duplicate by URL and hand off to the existing enrichment /
SmartExtract pipeline via the normal ``insert_jobs`` call.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import urllib.parse as urlparse
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from bs4 import BeautifulSoup

from ..core.database import insert_jobs
from ..core.profile import Profile

if TYPE_CHECKING:
    from ..browser.driver import BrowserFactory

log = logging.getLogger(__name__)

ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "jobs.workable.com", "boards.greenhouse.io")

# ---------------------------------------------------------------------------
# Browser-fallback configuration (no API key, no rate-limit surfacing).
# ---------------------------------------------------------------------------

#: Endpoints the undetected browser scrapes. DuckDuckGo's HTML endpoint is the
#: PRIMARY source (scraper-friendly, stable markup); Google is a secondary
#: source that frequently hides results behind a consent wall — handled
#: gracefully (warn + continue, never raise).
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
GOOGLE_SEARCH_URL = "https://www.google.com/search"

#: ATS / job-board hosts we trust as "real job postings". A superset of
#: :data:`ATS_HOSTS` covering the permitted ATS domains in the spec plus the
#: common variants their results show up under.
ATS_JOB_HOSTS: tuple[str, ...] = (
    "lever.co",
    "jobs.lever.co",
    "greenhouse.io",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "ashbyhq.com",
    "jobs.ashbyhq.com",
    "workable.com",
    "jobs.workable.com",
    "smartrecruiters.com",
    "myworkdayjobs.com",
    "icims.com",
    "taleo.net",
    "bamboohr.com",
    "breezy.hr",
    "recruitee.com",
    "jobvite.com",
)

#: Site-filter clause biased to the permitted ATS domains. Appended to a
#: subset of queries to surface direct ATS postings; the un-filtered queries
#: catch company career pages.
ATS_SITE_FILTER = (
    "site:lever.co OR site:greenhouse.io OR site:ashbyhq.com OR "
    "site:jobs.ashbyhq.com OR site:boards.greenhouse.io OR site:job-boards.greenhouse.io"
)

#: Search-engine / aggregator / social hosts we never treat as job postings.
_NOISE_HOSTS: tuple[str, ...] = (
    "google.",
    "google.com",
    "duckduckgo.com",
    "bing.com",
    "youtube.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "reddit.com",
    "indeed.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "wikipedia.org",
    "medium.com",
    "quora.com",
    "pinterest.com",
    "amazon.com",
    "microsoft.com/en-us/search",
)


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]: ...


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY", "")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        body = {"api_key": self.api_key, "query": query, "max_results": max_results}
        try:
            resp = httpx.post("https://api.tavily.com/search", json=body, timeout=self.timeout)
        except httpx.HTTPError as e:
            log.warning("tavily transport: %s", e)
            return []
        if resp.status_code >= 400:
            log.warning("tavily http %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json() or {}
        return [
            {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content")}
            for r in data.get("results", [])
            if r.get("url")
        ]


class BraveProvider:
    name = "brave"

    def __init__(self, api_key: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        params = {"q": query, "count": min(max_results, 20)}
        try:
            resp = httpx.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            log.warning("brave transport: %s", e)
            return []
        if resp.status_code >= 400:
            log.warning("brave http %s: %s", resp.status_code, resp.text[:200])
            return []
        data = resp.json() or {}
        web = (data.get("web") or {}).get("results", [])
        return [
            {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("description")} for r in web if r.get("url")
        ]


class DuckDuckGoProvider:
    name = "duckduckgo"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        params = {"q": query}
        try:
            resp = httpx.get(
                "https://duckduckgo.com/html/",
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
        except httpx.HTTPError as e:
            log.warning("ddg transport: %s", e)
            return []
        if resp.status_code >= 400:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        out: list[dict[str, Any]] = []
        for a in soup.select("a.result__a")[:max_results]:
            href = a.get("href")
            if not href:
                continue
            # DuckDuckGo wraps URLs in /l/?uddg=…; unwrap.
            parsed = urlparse.urlparse(str(href))
            qs = urlparse.parse_qs(parsed.query)
            real = qs.get("uddg", [str(href)])[0]
            out.append({"url": real, "title": a.get_text(strip=True), "snippet": None})
        return out


class SearXNGProvider:
    name = "searxng"

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        self.base_url = (base_url or os.environ.get("SEARXNG_URL", "")).rstrip("/")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        if not self.base_url:
            return []
        try:
            resp = httpx.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            log.warning("searxng transport: %s", e)
            return []
        if resp.status_code >= 400:
            return []
        data = resp.json() or {}
        return [
            {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content")}
            for r in data.get("results", [])[:max_results]
            if r.get("url")
        ]


class GoogleCSEProvider:
    name = "google_cse"

    def __init__(self, api_key: str | None = None, cx: str | None = None, timeout: float = 30.0) -> None:
        self.api_key = api_key or os.environ.get("GOOGLE_CSE_KEY", "")
        self.cx = cx or os.environ.get("GOOGLE_CSE_CX", "")
        self.timeout = timeout

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        if not (self.api_key and self.cx):
            return []
        params = {"key": self.api_key, "cx": self.cx, "q": query, "num": min(10, max_results)}
        try:
            resp = httpx.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=self.timeout)
        except httpx.HTTPError as e:
            log.warning("google_cse transport: %s", e)
            return []
        if resp.status_code >= 400:
            return []
        data = resp.json() or {}
        return [
            {"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet")}
            for r in data.get("items", [])
            if r.get("link")
        ]


# ---------------------------------------------------------------------------
# Browser-driven fallback (no API key required)
# ---------------------------------------------------------------------------


class BrowserSearchProvider:
    """Last-resort search provider — drives an undetected Chrome at Google/DDG.

    Used only when every API provider above returns empty or is unconfigured.
    Two passes:

    * DuckDuckGo: ``https://duckduckgo.com/?q=<q>`` — parse
      ``a[data-testid="result-title-a"]``.
    * Google: ``https://www.google.com/search?q=<q>`` — parse ``a:has(h3)``.

    The factory parameter accepts any :class:`browser.driver.BrowserFactory`
    so tests inject a fake driver returning canned HTML.
    """

    name = "browser"

    def __init__(
        self,
        *,
        factory: BrowserFactory | None = None,
        headless: bool = True,
        settle_seconds: float = 1.5,
    ) -> None:
        self.factory = factory
        self.headless = headless
        self.settle_seconds = settle_seconds

    def _build_factory(self) -> BrowserFactory | None:
        if self.factory is not None:
            return self.factory
        try:
            from ..browser.driver import UndetectedFactory

            return UndetectedFactory()
        except Exception as e:
            log.info("browser search: no factory available (%s)", e)
            return None

    def _scrape(self, driver: Any, *, query: str, max_results: int) -> list[dict[str, Any]]:
        import time as _time

        encoded = urlparse.quote_plus(query)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        for url, selector, kind in (
            (f"https://duckduckgo.com/?q={encoded}", 'a[data-testid="result-title-a"]', "ddg"),
            (f"https://www.google.com/search?q={encoded}", "a:has(h3)", "google"),
        ):
            try:
                driver.get(url)
            except Exception as e:
                log.debug("browser search nav (%s) failed: %s", kind, e)
                continue
            _time.sleep(max(0.0, self.settle_seconds))
            html = ""
            try:
                html = str(getattr(driver, "page_source", "") or "")
            except Exception:
                html = ""
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            for anchor in soup.select(selector):
                href = anchor.get("href")
                if not href:
                    continue
                href = str(href)
                # Google sometimes wraps in /url?q=…&sa=...; unwrap.
                if href.startswith("/url?"):
                    qs = urlparse.parse_qs(urlparse.urlparse(href).query)
                    real = qs.get("q") or qs.get("url")
                    href = str(real[0]) if real else href
                if not href.startswith(("http://", "https://")):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                title = anchor.get_text(" ", strip=True) or ""
                out.append({"url": href, "title": title, "snippet": None})
                if len(out) >= max_results:
                    return out
        return out

    def search(self, query: str, max_results: int = 20) -> list[dict[str, Any]]:
        factory = self._build_factory()
        if factory is None:
            return []
        try:
            driver = factory.make(headless=self.headless)
        except Exception as e:
            log.info("browser search: factory.make failed (%s)", e)
            return []
        try:
            return self._scrape(driver, query=query, max_results=max_results)
        finally:
            with suppress(Exception):
                driver.quit()


PROVIDER_BUILDERS: dict[str, type[Any]] = {
    "tavily": TavilyProvider,
    "brave": BraveProvider,
    "duckduckgo": DuckDuckGoProvider,
    "searxng": SearXNGProvider,
    "google_cse": GoogleCSEProvider,
    "browser": BrowserSearchProvider,
}


def build_chain(provider_names: list[str]) -> list[SearchProvider]:
    chain: list[SearchProvider] = []
    for name in provider_names:
        builder = PROVIDER_BUILDERS.get(name)
        if not builder:
            continue
        try:
            chain.append(builder())
        except Exception as e:
            log.warning("could not build provider %s: %s", name, e)
    return chain


def build_queries(profile: Profile, *, after_days: int = 14) -> list[str]:
    """Cartesian product of queries × locations × ATS sites."""
    out: list[str] = []
    for q in profile.search.queries:
        for loc in profile.search.locations:
            for site in ATS_HOSTS:
                out.append(f'"{q.q}" {loc.q} site:{site} after:{after_days}days')
    return out


def _is_ats_host(url: str) -> bool:
    try:
        host = urlparse.urlparse(url).hostname or ""
    except ValueError:
        return False
    return any(h in host for h in ATS_HOSTS)


# ---------------------------------------------------------------------------
# Pure parsing / URL helpers — unit-testable without a browser or network.
# ---------------------------------------------------------------------------


def decode_uddg(href: str) -> str:
    """Decode a DuckDuckGo ``/l/?uddg=<encoded>`` redirect to the real URL.

    DDG wraps every external result in ``/l/?uddg=<percent-encoded-url>`` (and
    sometimes ``&rut=...``). If the link isn't a DDG redirect it's returned
    unchanged. Never raises.
    """
    if not href:
        return ""
    try:
        parsed = urlparse.urlparse(href)
        qs = urlparse.parse_qs(parsed.query)
        real = qs.get("uddg")
        if real and real[0]:
            return urlparse.unquote(real[0])
    except (ValueError, TypeError):
        return href
    return href


def decode_google_url(href: str) -> str:
    """Decode a Google ``/url?q=<encoded>&sa=...`` redirect to the real URL.

    Modern Google results are direct ``http(s)`` links, but the classic and
    consent-redirected layouts still wrap the destination in ``/url?q=``.
    Returns the input unchanged when it isn't a Google redirect. Never raises.
    """
    if not href:
        return ""
    try:
        if href.startswith("/url?") or href.startswith("https://www.google.com/url?"):
            qs = urlparse.parse_qs(urlparse.urlparse(href).query)
            real = qs.get("q") or qs.get("url")
            if real and real[0]:
                return urlparse.unquote(real[0])
    except (ValueError, TypeError):
        return href
    return href


def is_job_posting_url(url: str) -> bool:
    """True when ``url`` looks like a real ATS / job-board posting.

    Keeps known ATS / job-board hosts; drops search-engine, aggregator and
    social noise. Anything that is neither clearly noise nor a known ATS host
    is rejected here (the browser fallback biases hard toward ATS domains via
    the ``site:`` filter, so this conservative filter keeps the queue clean).
    Never raises.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if any(n in host for n in _NOISE_HOSTS):
        return False
    return any(h in host for h in ATS_JOB_HOSTS)


def site_for_url(url: str) -> str:
    """Return the ATS name (if recognised) or the bare hostname for ``site``."""
    try:
        host = (urlparse.urlparse(url).hostname or "").lower()
    except ValueError:
        return "websearch"
    if not host:
        return "websearch"
    for ats in ("greenhouse", "lever", "ashby", "workable", "workday", "smartrecruiters", "icims", "taleo"):
        if ats in host:
            return ats
    return host


def parse_ddg_html(html: str, *, max_results: int = 20) -> list[dict[str, Any]]:
    """Extract result anchors from a DuckDuckGo HTML-endpoint response.

    Handles both the classic HTML endpoint markup (``a.result__a`` wrapped in
    ``/l/?uddg=`` redirects) and the lite ``data-testid`` markup. Returns a
    list of ``{"url", "title", "snippet"}`` dicts with decoded URLs. Never
    raises — a parse error yields an empty list.
    """
    if not html:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:  # pragma: no cover — lxml always present, defensive
        log.warning("ddg parse failed: %s", e)
        return []
    anchors = soup.select("a.result__a, a.result__url, a[data-testid='result-title-a']")
    for a in anchors:
        raw = a.get("href")
        if not raw:
            continue
        url = decode_uddg(str(raw))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": a.get_text(" ", strip=True) or "", "snippet": None})
        if len(out) >= max_results:
            break
    return out


def parse_google_html(html: str, *, max_results: int = 20) -> list[dict[str, Any]]:
    """Extract result anchors from a Google search-results page.

    Handles the classic ``a[href^='/url?q=']`` redirect layout and the modern
    ``div#search a[href^='http']`` (anchors wrapping an ``<h3>``) layout. If the
    page is a consent wall or has no parseable results an empty list is
    returned (the caller logs + continues — never a rate-limit error). Never
    raises.
    """
    if not html:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as e:  # pragma: no cover — defensive
        log.warning("google parse failed: %s", e)
        return []
    anchors: list[Any] = []
    anchors.extend(soup.select("a[href^='/url?q=']"))
    anchors.extend(soup.select("a[href^='https://www.google.com/url?']"))
    search_root = soup.select_one("div#search") or soup
    anchors.extend(a for a in search_root.select("a[href^='http']") if a.find("h3") is not None)
    for a in anchors:
        raw = a.get("href")
        if not raw:
            continue
        url = decode_google_url(str(raw))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        h3 = a.find("h3")
        title = (h3.get_text(" ", strip=True) if h3 else a.get_text(" ", strip=True)) or ""
        out.append({"url": url, "title": title, "snippet": None})
        if len(out) >= max_results:
            break
    return out


def build_browser_queries(profile: Profile, *, limit: int = 0) -> list[str]:
    """Build the query strings for the browser fallback.

    For every ``query × location`` we emit two variants: one biased to the
    permitted ATS domains via :data:`ATS_SITE_FILTER` (to catch direct ATS
    postings) and one un-filtered (to catch company career pages). The list is
    capped by ``profile.search.boards.websearch.queries_per_day`` and, when
    positive, the ``limit`` argument.
    """
    cap = max(0, profile.search.boards.websearch.queries_per_day)
    if cap == 0:
        # A zero daily cap means "do not run" — same semantics as run_websearch.
        return []
    out: list[str] = []
    for q in profile.search.queries:
        for loc in profile.search.locations:
            base = f"{q.q} {loc.q}".strip()
            out.append(f"{base} ({ATS_SITE_FILTER})")
            out.append(base)
    out = out[:cap]
    if limit and limit > 0:
        out = out[:limit]
    return out


def run_websearch(
    profile: Profile,
    *,
    conn: sqlite3.Connection,
    after_days: int = 14,
    max_results_per_query: int = 20,
    browser_factory: BrowserFactory | None = None,
) -> tuple[int, int]:
    """Run the websearch engine. Returns ``(new, dup)``.

    Honours the daily cap from ``profile.search.boards.websearch.queries_per_day``
    by truncating the query list. If every API provider returns empty, falls
    back to a browser-driven Google/DDG scrape capped at the same query
    budget.
    """
    cap = max(0, profile.search.boards.websearch.queries_per_day)
    queries = build_queries(profile, after_days=after_days)[:cap] if cap else []
    if not queries:
        return 0, 0
    chain = build_chain(profile.search.boards.websearch.providers)
    # Always have the browser fallback ready, even if not in the configured
    # chain — it's the lowest-priority safety net per the user's spec.
    browser_provider = BrowserSearchProvider(factory=browser_factory)

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat()

    for q in queries:
        results: list[dict[str, Any]] = []
        for provider in chain:
            try:
                results = provider.search(q, max_results=max_results_per_query)
            except Exception as e:
                log.warning("provider %s failed for %s: %s", provider.name, q, e)
                results = []
            if results:
                break
        # If everything else returned empty, drive the browser as a last
        # resort. Skip if a browser provider was already in the chain (no
        # point hitting Chrome twice for the same query).
        if not results and not any(p.name == BrowserSearchProvider.name for p in chain):
            try:
                results = browser_provider.search(q, max_results=max_results_per_query)
            except Exception as e:
                log.warning("browser fallback failed for %s: %s", q, e)
                results = []
        for r in results:
            url = r.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            row: dict[str, Any] = {
                "url": url,
                "title": r.get("title") or "",
                "salary": None,
                "description": r.get("snippet"),
                "location": "",
                "site": "websearch",
                "strategy": "websearch",
                "discovered_at": now,
                "web_search_query": q,
            }
            # Tag ATS hosts for fast-path enrichment downstream.
            if _is_ats_host(url):
                row["site"] = urlparse.urlparse(url).hostname or "websearch"
            rows.append(row)

    if not rows:
        return 0, 0
    return insert_jobs(rows, conn=conn)


# ---------------------------------------------------------------------------
# Browser-driven WebSearch engine (no API keys, no rate-limit errors).
#
# This is the path used when ``profile.search.boards.websearch.providers == []``:
# it drives the undetected browser at the DuckDuckGo HTML endpoint (primary) and
# Google (secondary), reusing one session across all queries with small
# randomized human-like delays. Every network/parse failure is caught and
# logged at WARNING — a rate-limit, consent wall or transport error never
# propagates to the caller.
# ---------------------------------------------------------------------------

#: Bounded retry budget per engine navigation + small backoff base (seconds).
_NAV_RETRIES = 2
_NAV_BACKOFF = 0.6
#: Human-like inter-query delay window (seconds) to avoid tripping bot
#: detection. Multiplied to ~0 in tests via ``delay_range=(0.0, 0.0)``.
_DELAY_RANGE = (0.8, 2.2)


def _looks_like_consent_wall(html: str) -> bool:
    """Heuristic: True when a Google response is a consent/redirect interstitial."""
    if not html:
        return False
    lowered = html[:4000].lower()
    markers = ("consent.google.com", "before you continue", 'id="cnsw"', "accept all", "consent.youtube.com")
    return any(m in lowered for m in markers)


class BrowserWebSearch:
    """Undetected-browser search engine over DDG (primary) + Google (secondary).

    Reuses a single browser session across every query. The ``factory``
    parameter accepts any :class:`browser.driver.BrowserFactory`, so tests
    inject a fake whose ``.get(url)`` flips ``.page_source`` to canned HTML.
    Nothing here raises: each failure is caught and logged at WARNING.
    """

    name = "websearch_browser"

    def __init__(
        self,
        *,
        factory: BrowserFactory | None = None,
        headless: bool = True,
        settle_seconds: float = 1.2,
        delay_range: tuple[float, float] = _DELAY_RANGE,
        retries: int = _NAV_RETRIES,
    ) -> None:
        self.factory = factory
        self.headless = headless
        self.settle_seconds = settle_seconds
        self.delay_range = delay_range
        self.retries = max(0, retries)

    # -- factory / session -------------------------------------------------

    def _build_factory(self) -> BrowserFactory | None:
        if self.factory is not None:
            return self.factory
        try:
            from ..browser.driver import UndetectedFactory

            return UndetectedFactory()
        except Exception as e:
            log.warning("websearch browser: no factory available (%s)", e)
            return None

    # -- low-level fetch (bounded retries, never raises) -------------------

    def _fetch(self, driver: Any, url: str, *, kind: str) -> str:
        import time as _time

        for attempt in range(self.retries + 1):
            try:
                driver.get(url)
            except Exception as e:
                log.warning("websearch browser nav (%s) failed [try %d]: %s", kind, attempt + 1, e)
                if attempt < self.retries:
                    _time.sleep(_NAV_BACKOFF * (attempt + 1))
                continue
            _time.sleep(max(0.0, self.settle_seconds))
            try:
                html = str(getattr(driver, "page_source", "") or "")
            except Exception as e:
                log.warning("websearch browser page_source (%s) failed: %s", kind, e)
                html = ""
            if html:
                return html
            if attempt < self.retries:
                _time.sleep(_NAV_BACKOFF * (attempt + 1))
        return ""

    # -- per-query scrape --------------------------------------------------

    def search_one(self, driver: Any, query: str, *, max_results: int = 20) -> list[dict[str, Any]]:
        """Scrape DDG (primary) then Google (secondary) for a single query.

        Returns deduped ``{"url", "title", "snippet"}`` dicts filtered to
        plausible job-posting URLs. Never raises.
        """
        encoded = urlparse.quote_plus(query)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        # 1) DuckDuckGo HTML endpoint — PRIMARY, scraper-friendly.
        ddg_url = f"{DDG_HTML_URL}?q={encoded}"
        ddg_html = self._fetch(driver, ddg_url, kind="ddg")
        for r in parse_ddg_html(ddg_html, max_results=max_results):
            url = r["url"]
            if url in seen or not is_job_posting_url(url):
                continue
            seen.add(url)
            out.append(r)
            if len(out) >= max_results:
                return out

        # 2) Google — SECONDARY. Consent walls / no results are non-fatal.
        google_url = f"{GOOGLE_SEARCH_URL}?q={encoded}&num=20"
        google_html = self._fetch(driver, google_url, kind="google")
        if _looks_like_consent_wall(google_html):
            log.warning("websearch browser: google consent wall for %r; skipping google for this query", query)
            google_html = ""
        google_results = parse_google_html(google_html, max_results=max_results)
        if not google_results and google_html:
            log.warning("websearch browser: no parseable google results for %r", query)
        for r in google_results:
            url = r["url"]
            if url in seen or not is_job_posting_url(url):
                continue
            seen.add(url)
            out.append(r)
            if len(out) >= max_results:
                break
        return out

    # -- multi-query run, single shared session ---------------------------

    def run(
        self,
        queries: list[str],
        *,
        max_results_per_query: int = 20,
    ) -> list[dict[str, Any]]:
        """Run every query through one shared browser session. Never raises."""
        import random
        import time as _time

        if not queries:
            return []
        factory = self._build_factory()
        if factory is None:
            return []
        try:
            driver = factory.make(headless=self.headless)
        except Exception as e:
            log.warning("websearch browser: factory.make failed (%s); returning no results", e)
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            for i, q in enumerate(queries):
                try:
                    found = self.search_one(driver, q, max_results=max_results_per_query)
                except Exception as e:  # defensive — search_one already guards
                    log.warning("websearch browser: query %r failed: %s", q, e)
                    found = []
                for r in found:
                    if r["url"] in seen:
                        continue
                    seen.add(r["url"])
                    r["web_search_query"] = q
                    results.append(r)
                # Human-like delay between queries (skip after the last one).
                lo, hi = self.delay_range
                if i < len(queries) - 1 and hi > 0:
                    _time.sleep(random.uniform(max(0.0, lo), hi))
        finally:
            with suppress(Exception):
                driver.quit()
        return results


def run_browser_websearch(
    profile: Profile,
    *,
    conn: sqlite3.Connection,
    router: Any | None = None,
    limit: int = 0,
    max_results_per_query: int = 20,
    browser_factory: BrowserFactory | None = None,
) -> tuple[int, int]:
    """Browser-only discovery via DDG + Google. Returns ``(new, dup)``.

    Used when no search-API providers are configured. Builds ATS-biased and
    un-filtered queries, drives the undetected browser (one shared session),
    keeps only plausible job-posting URLs, de-dups and inserts. Returns
    ``(0, 0)`` gracefully when the browser is unavailable or nothing matched.
    Never raises a rate-limit (or any) error to the caller.
    """
    _ = router  # accepted for entrypoint-signature parity; unused here.
    queries = build_browser_queries(profile, limit=limit)
    if not queries:
        return 0, 0

    engine = BrowserWebSearch(factory=browser_factory, headless=profile.apply.headless)
    try:
        found = engine.run(queries, max_results_per_query=max_results_per_query)
    except Exception as e:  # defensive — engine.run already guards everything.
        log.warning("websearch browser engine failed: %s", e)
        return 0, 0
    if not found:
        return 0, 0

    now = datetime.now(UTC).isoformat()
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for r in found:
        url = r.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(
            {
                "url": url,
                "title": r.get("title") or "",
                "salary": None,
                "description": r.get("snippet"),
                "location": "",
                "site": site_for_url(url),
                "strategy": "websearch_browser",
                "discovered_at": now,
                "web_search_query": r.get("web_search_query"),
            }
        )
    if not rows:
        return 0, 0
    try:
        return insert_jobs(rows, conn=conn)
    except Exception as e:  # defensive — DB errors shouldn't surface to user.
        log.warning("websearch browser insert failed: %s", e)
        return 0, 0
