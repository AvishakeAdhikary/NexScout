"""Browser-driven WebSearch fallback (§8.4 + Task-2 spec)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.discovery.websearch import BrowserSearchProvider, run_websearch

# ---------------------------------------------------------------------------
# Fake driver / factory
# ---------------------------------------------------------------------------


class _FakeDriver:
    """A driver mock whose ``page_source`` swaps based on the URL we navigate."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.current_url = ""
        self.calls: list[str] = []

    def get(self, url: str) -> None:
        self.calls.append(url)
        self.current_url = url

    @property
    def page_source(self) -> str:
        # Pick the response whose key is a substring of the current URL.
        for key, html in self.pages.items():
            if key in self.current_url:
                return html
        return ""

    def quit(self) -> None:
        pass


class _FakeFactory:
    def __init__(self, driver: _FakeDriver) -> None:
        self.driver = driver
        self.headless_calls: list[bool] = []

    def make(self, *, headless: bool = True) -> Any:
        self.headless_calls.append(headless)
        return self.driver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def profile_with_websearch() -> Profile:
    """A minimal profile with no API keys, one query, one location."""
    return Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@e.com", "phone": "1"},
            "search": {
                "queries": [{"q": "platform engineer", "tier": 1}],
                "locations": [{"label": "Remote", "q": "Remote", "remote": True}],
                "boards": {
                    "websearch": {"providers": [], "queries_per_day": 5},
                },
            },
        }
    )


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    return init_db(tmp_path / ".nexscout" / "ws.sqlite")


# ---------------------------------------------------------------------------
# BrowserSearchProvider unit tests
# ---------------------------------------------------------------------------


def test_browser_provider_scrapes_ddg_and_google() -> None:
    ddg_html = """
    <html><body>
      <a data-testid="result-title-a" href="https://boards.greenhouse.io/acme/jobs/1">Acme</a>
      <a data-testid="result-title-a" href="https://jobs.lever.co/foo/2">Lever foo</a>
    </body></html>
    """
    google_html = """
    <html><body>
      <a href="https://www.ashbyhq.com/bar/3"><h3>Bar Ashby</h3></a>
      <a href="/url?q=https://jobs.workable.com/baz/4&sa=U"><h3>Workable baz</h3></a>
    </body></html>
    """
    driver = _FakeDriver({"duckduckgo.com": ddg_html, "google.com": google_html})
    factory = _FakeFactory(driver)
    provider = BrowserSearchProvider(factory=factory, settle_seconds=0.0)

    out = provider.search("staff engineer", max_results=10)
    urls = {r["url"] for r in out}
    assert "https://boards.greenhouse.io/acme/jobs/1" in urls
    assert "https://jobs.lever.co/foo/2" in urls
    assert "https://www.ashbyhq.com/bar/3" in urls
    assert "https://jobs.workable.com/baz/4" in urls
    # Hit both engines.
    assert any("duckduckgo.com" in c for c in driver.calls)
    assert any("google.com/search" in c for c in driver.calls)


def test_browser_provider_returns_empty_when_no_factory() -> None:
    provider = BrowserSearchProvider(factory=None)
    # Without a real Chrome the factory build returns None and search yields [].
    # We can't be certain undetected_chromedriver isn't installed in the test
    # env, so we monkey-patch the build to None to force the fallback.
    provider.factory = None
    provider._build_factory = lambda: None  # type: ignore[method-assign]
    assert provider.search("anything") == []


def test_browser_provider_caps_max_results() -> None:
    html = "".join(f'<a data-testid="result-title-a" href="https://greenhouse.io/x/{i}">{i}</a>' for i in range(30))
    driver = _FakeDriver({"duckduckgo.com": f"<html><body>{html}</body></html>"})
    factory = _FakeFactory(driver)
    provider = BrowserSearchProvider(factory=factory, settle_seconds=0.0)
    out = provider.search("q", max_results=5)
    assert len(out) == 5


# ---------------------------------------------------------------------------
# run_websearch fallback wiring
# ---------------------------------------------------------------------------


def test_run_websearch_uses_browser_when_no_api_providers(
    conn: sqlite3.Connection, profile_with_websearch: Profile
) -> None:
    """No API providers configured → browser fallback should still produce rows."""
    ddg_html = """
    <html><body>
      <a data-testid="result-title-a" href="https://boards.greenhouse.io/acme/jobs/77">Acme 77</a>
    </body></html>
    """
    driver = _FakeDriver({"duckduckgo.com": ddg_html})
    factory = _FakeFactory(driver)

    new, _dup = run_websearch(
        profile_with_websearch,
        conn=conn,
        browser_factory=factory,
    )
    assert new >= 1
    # Verify the row landed with strategy=websearch and host-derived site.
    rows = conn.execute("SELECT url, site, strategy, web_search_query FROM jobs").fetchall()
    assert any("greenhouse" in (r["site"] or "") for r in rows)
    assert all(r["strategy"] == "websearch" for r in rows)


def test_run_websearch_respects_daily_cap(conn: sqlite3.Connection, profile_with_websearch: Profile) -> None:
    profile_with_websearch.search.boards.websearch.queries_per_day = 0
    result = run_websearch(profile_with_websearch, conn=conn)
    assert result == (0, 0)
