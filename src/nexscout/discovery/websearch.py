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
