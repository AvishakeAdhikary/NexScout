"""Hermetic unit tests for the browser-driven WebSearch engine.

These tests feed canned DuckDuckGo + Google HTML into the pure parser
functions and drive the :class:`BrowserWebSearch` engine through a fake
browser (no real Chrome, no network). They lock in:

* DDG ``/l/?uddg=`` and Google ``/url?q=`` redirect decoding,
* DDG-HTML-endpoint (primary) + Google (secondary) anchor extraction,
* ATS / job-posting URL filtering + de-duplication,
* single-session reuse across queries with no human-delay in tests,
* graceful no-browser / consent-wall / nav-failure handling (never raises),
* the ``run_browser_websearch`` entrypoint writing ``strategy='websearch_browser'``
  rows via ``database.insert_jobs``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.discovery import websearch as ws

# ---------------------------------------------------------------------------
# Fake browser / factory
# ---------------------------------------------------------------------------


class _FakeDriver:
    """Driver whose ``page_source`` is selected by substring of the nav URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.current_url = ""
        self.calls: list[str] = []
        self.quit_called = 0

    def get(self, url: str) -> None:
        self.calls.append(url)
        self.current_url = url

    @property
    def page_source(self) -> str:
        for key, html in self.pages.items():
            if key in self.current_url:
                return html
        return ""

    def quit(self) -> None:
        self.quit_called += 1


class _FakeFactory:
    def __init__(self, driver: _FakeDriver) -> None:
        self.driver = driver
        self.make_calls = 0
        self.headless_calls: list[bool] = []

    def make(self, *, headless: bool = True) -> Any:
        self.make_calls += 1
        self.headless_calls.append(headless)
        return self.driver


# ---------------------------------------------------------------------------
# Canned HTML snippets
# ---------------------------------------------------------------------------

DDG_HTML = """
<html><body>
  <div class="result">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fboards.greenhouse.io%2Facme%2Fjobs%2F1&amp;rut=x">Acme Eng</a>
  </div>
  <div class="result">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Ffoo%2F2">Lever Foo</a>
  </div>
  <div class="result">
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fwww.reddit.com%2Fr%2Fjobs%2Fpost">Reddit noise</a>
  </div>
</body></html>
"""

GOOGLE_HTML = """
<html><body>
  <div id="search">
    <a href="/url?q=https://jobs.ashbyhq.com/bar/3&amp;sa=U&amp;ved=x"><h3>Bar Ashby</h3></a>
    <a href="https://job-boards.greenhouse.io/baz/4"><h3>Baz GH</h3></a>
    <a href="https://www.google.com/search?q=more"><h3>Google noise</h3></a>
  </div>
</body></html>
"""

GOOGLE_CONSENT_HTML = """
<html><body>
  <div id="cnsw">Before you continue to Google
    <form action="https://consent.google.com/save"><button>Accept all</button></form>
  </div>
</body></html>
"""


# ---------------------------------------------------------------------------
# URL decoders
# ---------------------------------------------------------------------------


def test_decode_uddg_unwraps_redirect() -> None:
    href = "/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Ffoo%2F2&rut=abc"
    assert ws.decode_uddg(href) == "https://jobs.lever.co/foo/2"


def test_decode_uddg_passthrough_for_plain_url() -> None:
    assert ws.decode_uddg("https://example.com/x") == "https://example.com/x"


def test_decode_uddg_empty() -> None:
    assert ws.decode_uddg("") == ""


def test_decode_google_url_unwraps_redirect() -> None:
    href = "/url?q=https://jobs.ashbyhq.com/bar/3&sa=U&ved=2"
    assert ws.decode_google_url(href) == "https://jobs.ashbyhq.com/bar/3"


def test_decode_google_url_passthrough_for_direct_link() -> None:
    assert ws.decode_google_url("https://boards.greenhouse.io/x/1") == "https://boards.greenhouse.io/x/1"


def test_decode_google_url_full_wrapper() -> None:
    href = "https://www.google.com/url?q=https://jobs.lever.co/y/2&sa=U"
    assert ws.decode_google_url(href) == "https://jobs.lever.co/y/2"


# ---------------------------------------------------------------------------
# ATS / job-posting filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://jobs.lever.co/foo/2",
        "https://jobs.ashbyhq.com/bar/3",
        "https://job-boards.greenhouse.io/baz/4",
        "https://company.myworkdayjobs.com/job/5",
        "https://jobs.workable.com/baz/6",
    ],
)
def test_is_job_posting_url_accepts_ats(url: str) -> None:
    assert ws.is_job_posting_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.google.com/search?q=x",
        "https://www.reddit.com/r/jobs/post",
        "https://www.linkedin.com/jobs/view/1",
        "https://www.indeed.com/viewjob?jk=1",
        "https://en.wikipedia.org/wiki/Job",
        "ftp://greenhouse.io/x",
        "not a url",
        "",
    ],
)
def test_is_job_posting_url_rejects_noise(url: str) -> None:
    assert ws.is_job_posting_url(url) is False


def test_site_for_url_maps_ats_name() -> None:
    assert ws.site_for_url("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert ws.site_for_url("https://jobs.lever.co/foo/2") == "lever"
    assert ws.site_for_url("https://jobs.ashbyhq.com/bar/3") == "ashby"


def test_site_for_url_falls_back_to_host() -> None:
    assert ws.site_for_url("https://careers.bigco.com/x") == "careers.bigco.com"


# ---------------------------------------------------------------------------
# Pure HTML parsers
# ---------------------------------------------------------------------------


def test_parse_ddg_html_extracts_and_decodes() -> None:
    out = ws.parse_ddg_html(DDG_HTML)
    urls = [r["url"] for r in out]
    assert "https://boards.greenhouse.io/acme/jobs/1" in urls
    assert "https://jobs.lever.co/foo/2" in urls
    # Parser itself does NOT filter noise — it just extracts/decodes.
    assert "https://www.reddit.com/r/jobs/post" in urls
    assert all(set(r) == {"url", "title", "snippet"} for r in out)


def test_parse_ddg_html_handles_data_testid_markup() -> None:
    html = '<a data-testid="result-title-a" href="https://jobs.lever.co/foo/9">Foo</a>'
    out = ws.parse_ddg_html(html)
    assert out and out[0]["url"] == "https://jobs.lever.co/foo/9"


def test_parse_ddg_html_dedupes() -> None:
    html = (
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Fa%2F1">A</a>'
        '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Fa%2F1">A again</a>'
    )
    out = ws.parse_ddg_html(html)
    assert len(out) == 1


def test_parse_ddg_html_respects_max_results() -> None:
    html = "".join(
        f'<a class="result__a" href="/l/?uddg=https%3A%2F%2Fjobs.lever.co%2Fx%2F{i}">{i}</a>' for i in range(30)
    )
    out = ws.parse_ddg_html(html, max_results=5)
    assert len(out) == 5


def test_parse_ddg_html_empty_input() -> None:
    assert ws.parse_ddg_html("") == []


def test_parse_google_html_extracts_redirect_and_modern() -> None:
    out = ws.parse_google_html(GOOGLE_HTML)
    urls = [r["url"] for r in out]
    assert "https://jobs.ashbyhq.com/bar/3" in urls  # /url?q= redirect
    assert "https://job-boards.greenhouse.io/baz/4" in urls  # modern div#search a
    assert any(r["title"] == "Bar Ashby" for r in out)


def test_parse_google_html_empty_for_consent_wall_markup() -> None:
    # The consent page has no result anchors → parser yields nothing.
    assert ws.parse_google_html(GOOGLE_CONSENT_HTML) == []


def test_parse_google_html_dedupes() -> None:
    html = (
        '<div id="search">'
        '<a href="/url?q=https://jobs.lever.co/a/1&sa=U"><h3>A</h3></a>'
        '<a href="https://jobs.lever.co/a/1"><h3>A dup</h3></a>'
        "</div>"
    )
    out = ws.parse_google_html(html)
    assert len(out) == 1


# ---------------------------------------------------------------------------
# build_browser_queries
# ---------------------------------------------------------------------------


def _profile(queries_per_day: int = 50, n_queries: int = 1, n_locs: int = 1) -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"},
            "search": {
                "queries": [{"q": f"engineer {i}", "tier": 1} for i in range(n_queries)],
                "locations": [{"label": f"L{i}", "q": f"Loc{i}", "remote": True} for i in range(n_locs)],
                "boards": {"websearch": {"providers": [], "queries_per_day": queries_per_day}},
            },
        }
    )


def test_build_browser_queries_filtered_and_unfiltered() -> None:
    qs = ws.build_browser_queries(_profile(n_queries=1, n_locs=1))
    # One ATS-filtered + one un-filtered variant per query×location.
    assert len(qs) == 2
    assert any(ws.ATS_SITE_FILTER in q for q in qs)
    assert any(ws.ATS_SITE_FILTER not in q for q in qs)


def test_build_browser_queries_respects_daily_cap() -> None:
    qs = ws.build_browser_queries(_profile(queries_per_day=1, n_queries=2, n_locs=2))
    assert len(qs) == 1


def test_build_browser_queries_respects_limit_arg() -> None:
    qs = ws.build_browser_queries(_profile(queries_per_day=50, n_queries=3, n_locs=2), limit=3)
    assert len(qs) == 3


def test_build_browser_queries_zero_cap_is_empty() -> None:
    assert ws.build_browser_queries(_profile(queries_per_day=0)) == []


# ---------------------------------------------------------------------------
# BrowserWebSearch engine
# ---------------------------------------------------------------------------


def test_engine_search_one_ddg_primary_google_secondary() -> None:
    driver = _FakeDriver({"html.duckduckgo.com": DDG_HTML, "google.com/search": GOOGLE_HTML})
    engine = ws.BrowserWebSearch(factory=_FakeFactory(driver), settle_seconds=0.0, delay_range=(0.0, 0.0))
    out = engine.search_one(driver, "platform engineer remote")
    urls = {r["url"] for r in out}
    # ATS links from both engines survive; noise (reddit, google) is filtered.
    assert "https://boards.greenhouse.io/acme/jobs/1" in urls
    assert "https://jobs.lever.co/foo/2" in urls
    assert "https://jobs.ashbyhq.com/bar/3" in urls
    assert "https://job-boards.greenhouse.io/baz/4" in urls
    assert not any("reddit" in u or "google.com" in u for u in urls)
    # Hit the DDG HTML endpoint first, then Google.
    assert any("html.duckduckgo.com/html" in c for c in driver.calls)
    assert any("google.com/search" in c and "num=20" in c for c in driver.calls)


def test_engine_consent_wall_skips_google_gracefully() -> None:
    driver = _FakeDriver({"html.duckduckgo.com": DDG_HTML, "google.com/search": GOOGLE_CONSENT_HTML})
    engine = ws.BrowserWebSearch(factory=_FakeFactory(driver), settle_seconds=0.0, delay_range=(0.0, 0.0))
    out = engine.search_one(driver, "engineer")
    urls = {r["url"] for r in out}
    # DDG results still present; consent wall contributes nothing and does not raise.
    assert "https://boards.greenhouse.io/acme/jobs/1" in urls
    assert all("consent" not in u for u in urls)


def test_engine_run_reuses_single_session_across_queries() -> None:
    driver = _FakeDriver({"html.duckduckgo.com": DDG_HTML, "google.com/search": GOOGLE_HTML})
    factory = _FakeFactory(driver)
    engine = ws.BrowserWebSearch(factory=factory, settle_seconds=0.0, delay_range=(0.0, 0.0))
    out = engine.run(["q1", "q2", "q3"], max_results_per_query=20)
    # Single browser session for all three queries.
    assert factory.make_calls == 1
    assert driver.quit_called == 1
    # Dedup across queries → unique ATS URLs only, each tagged with a query.
    assert out
    assert all(r.get("web_search_query") in {"q1", "q2", "q3"} for r in out)
    assert len({r["url"] for r in out}) == len(out)


def test_engine_run_no_factory_returns_empty() -> None:
    engine = ws.BrowserWebSearch(factory=None)
    engine._build_factory = lambda: None  # type: ignore[method-assign]
    assert engine.run(["q"]) == []


def test_engine_run_factory_make_failure_is_graceful() -> None:
    class _BadFactory:
        def make(self, *, headless: bool = True) -> Any:
            raise RuntimeError("no chrome")

    engine = ws.BrowserWebSearch(factory=_BadFactory())
    assert engine.run(["q"]) == []


def test_engine_search_one_nav_failure_never_raises() -> None:
    class _NavBoom:
        page_source = ""
        current_url = ""

        def get(self, url: str) -> None:
            raise RuntimeError("nav failed")

        def quit(self) -> None:
            pass

    engine = ws.BrowserWebSearch(factory=None, settle_seconds=0.0, delay_range=(0.0, 0.0), retries=1)
    assert engine.search_one(_NavBoom(), "q") == []


def test_engine_run_empty_queries() -> None:
    driver = _FakeDriver({})
    assert ws.BrowserWebSearch(factory=_FakeFactory(driver)).run([]) == []


# ---------------------------------------------------------------------------
# run_browser_websearch entrypoint
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> sqlite3.Connection:
    monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / ".nexscout"))
    return init_db(tmp_path / ".nexscout" / "ws.sqlite")


def test_run_browser_websearch_inserts_websearch_browser_rows(conn: sqlite3.Connection) -> None:
    driver = _FakeDriver({"html.duckduckgo.com": DDG_HTML, "google.com/search": GOOGLE_HTML})
    factory = _FakeFactory(driver)
    p = _profile(queries_per_day=2, n_queries=1, n_locs=1)

    new, _dup = ws.run_browser_websearch(p, conn=conn, browser_factory=factory)
    assert new >= 1
    rows = conn.execute("SELECT url, site, strategy, web_search_query FROM jobs").fetchall()
    assert rows
    assert all(r["strategy"] == "websearch_browser" for r in rows)
    # ATS hosts are tagged with the ATS name; noise never made it in.
    sites = {r["site"] for r in rows}
    assert "greenhouse" in sites or "lever" in sites or "ashby" in sites
    assert not any("reddit" in (r["url"] or "") for r in rows)
    assert all(r["web_search_query"] for r in rows)


def test_run_browser_websearch_dedupes_on_second_run(conn: sqlite3.Connection) -> None:
    driver = _FakeDriver({"html.duckduckgo.com": DDG_HTML, "google.com/search": GOOGLE_HTML})
    factory = _FakeFactory(driver)
    p = _profile(queries_per_day=2, n_queries=1, n_locs=1)

    new1, _ = ws.run_browser_websearch(p, conn=conn, browser_factory=_FakeFactory(driver))
    new2, dup2 = ws.run_browser_websearch(p, conn=conn, browser_factory=factory)
    assert new1 >= 1
    # Everything is already present → all duplicates on the second pass.
    assert new2 == 0
    assert dup2 >= 1


def test_run_browser_websearch_zero_cap_returns_zero(conn: sqlite3.Connection) -> None:
    p = _profile(queries_per_day=0)
    assert ws.run_browser_websearch(p, conn=conn) == (0, 0)


def test_run_browser_websearch_no_browser_returns_zero(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = _profile(queries_per_day=2)

    # Force the default factory build to fail (no real Chrome) → graceful (0, 0).
    def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("no Chrome")

    monkeypatch.setattr("nexscout.browser.driver.UndetectedFactory", _boom)
    assert ws.run_browser_websearch(p, conn=conn) == (0, 0)


def test_run_browser_websearch_no_results_returns_zero(conn: sqlite3.Connection) -> None:
    # DDG + Google both return only noise → nothing passes the ATS filter.
    noise = '<html><body><a class="result__a" href="/l/?uddg=https%3A%2F%2Freddit.com%2Fx">x</a></body></html>'
    driver = _FakeDriver({"html.duckduckgo.com": noise, "google.com/search": noise})
    p = _profile(queries_per_day=2)
    assert ws.run_browser_websearch(p, conn=conn, browser_factory=_FakeFactory(driver)) == (0, 0)
