"""Tests for ``discovery.websearch`` — provider chain + browser fallback."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.discovery import websearch as ws


def _profile(providers: list[str] | None = None, queries_per_day: int = 5) -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"},
            "search": {
                "queries": [{"q": "engineer", "tier": 1}],
                "locations": [{"label": "Remote", "q": "Remote", "remote": True}],
                "boards": {
                    "websearch": {
                        "providers": providers if providers is not None else ["tavily"],
                        "queries_per_day": queries_per_day,
                    }
                },
            },
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "x.sqlite")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Provider classes
# ---------------------------------------------------------------------------


def _make_resp(json_body: Any = None, status: int = 200, text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_body or {}
    return r


def test_tavily_no_key() -> None:
    assert ws.TavilyProvider(api_key="").search("q") == []


def test_tavily_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: _make_resp(
            json_body={"results": [{"url": "https://x.com", "title": "X", "content": "snippet"}]}
        ),
    )
    out = ws.TavilyProvider(api_key="k").search("q")
    assert out == [{"url": "https://x.com", "title": "X", "snippet": "snippet"}]


def test_tavily_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_resp(status=429))
    assert ws.TavilyProvider(api_key="k").search("q") == []


def test_tavily_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("broken")

    monkeypatch.setattr(httpx, "post", _boom)
    assert ws.TavilyProvider(api_key="k").search("q") == []


def test_brave_no_key() -> None:
    assert ws.BraveProvider(api_key="").search("q") == []


def test_brave_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _make_resp(
            json_body={"web": {"results": [{"url": "https://x.com", "title": "X", "description": "y"}]}}
        ),
    )
    out = ws.BraveProvider(api_key="k").search("q")
    assert out == [{"url": "https://x.com", "title": "X", "snippet": "y"}]


def test_brave_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("nope")

    monkeypatch.setattr(httpx, "get", _boom)
    assert ws.BraveProvider(api_key="k").search("q") == []


def test_brave_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _make_resp(status=500))
    assert ws.BraveProvider(api_key="k").search("q") == []


def test_duckduckgo_success(monkeypatch: pytest.MonkeyPatch) -> None:
    html = """
    <html><body>
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fx.com%2Fjob">X title</a>
    </body></html>
    """
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _make_resp(text=html))
    out = ws.DuckDuckGoProvider().search("q")
    assert out and out[0]["url"] == "https://x.com/job"


def test_duckduckgo_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _make_resp(status=503))
    assert ws.DuckDuckGoProvider().search("q") == []


def test_duckduckgo_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("dead")

    monkeypatch.setattr(httpx, "get", _boom)
    assert ws.DuckDuckGoProvider().search("q") == []


def test_searxng_no_url() -> None:
    assert ws.SearXNGProvider(base_url="").search("q") == []


def test_searxng_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _make_resp(json_body={"results": [{"url": "https://x.com", "title": "X", "content": "z"}]}),
    )
    out = ws.SearXNGProvider(base_url="https://searx.test").search("q")
    assert out == [{"url": "https://x.com", "title": "X", "snippet": "z"}]


def test_searxng_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("dead")

    monkeypatch.setattr(httpx, "get", _boom)
    assert ws.SearXNGProvider(base_url="https://x").search("q") == []


def test_google_cse_no_keys() -> None:
    assert ws.GoogleCSEProvider(api_key="", cx="").search("q") == []


def test_google_cse_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **kw: _make_resp(json_body={"items": [{"link": "https://x.com", "title": "X", "snippet": "y"}]}),
    )
    out = ws.GoogleCSEProvider(api_key="k", cx="c").search("q")
    assert out == [{"url": "https://x.com", "title": "X", "snippet": "y"}]


def test_google_cse_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("dead")

    monkeypatch.setattr(httpx, "get", _boom)
    assert ws.GoogleCSEProvider(api_key="k", cx="c").search("q") == []


# ---------------------------------------------------------------------------
# BrowserSearchProvider
# ---------------------------------------------------------------------------


def test_browser_provider_no_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the default ``UndetectedFactory`` import fails the provider returns []."""

    def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("no Chrome")

    monkeypatch.setattr("nexscout.browser.driver.UndetectedFactory", _boom)
    p = ws.BrowserSearchProvider(factory=None)
    assert p.search("q") == []


def test_browser_provider_drives_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)

    ddg_html = '<a data-testid="result-title-a" href="https://x.com/a">A</a>'
    google_html = '<a href="/url?q=https%3A%2F%2Fy.com%2Fb"><h3>B</h3></a>'

    state = {"n": 0}

    class _Drv:
        page_source = ""

        def get(self, url: str) -> None:
            state["n"] += 1
            self.page_source = ddg_html if state["n"] == 1 else google_html

        def quit(self) -> None:
            return None

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return _Drv()

    p = ws.BrowserSearchProvider(factory=_Fac())
    out = p.search("q", max_results=10)
    assert out
    assert any("x.com" in r["url"] for r in out)


def test_browser_provider_navigation_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)

    class _Drv:
        page_source = ""

        def get(self, url: str) -> None:
            raise RuntimeError("nav failed")

        def quit(self) -> None:
            return None

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return _Drv()

    out = ws.BrowserSearchProvider(factory=_Fac()).search("q")
    assert out == []


def test_browser_provider_factory_make_failure() -> None:
    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            raise RuntimeError("ouch")

    out = ws.BrowserSearchProvider(factory=_Fac()).search("q")
    assert out == []


# ---------------------------------------------------------------------------
# build_chain / build_queries / _is_ats_host
# ---------------------------------------------------------------------------


def test_build_chain_known_providers() -> None:
    chain = ws.build_chain(["tavily", "ddg-nope", "duckduckgo"])
    names = [p.name for p in chain]
    assert "tavily" in names
    assert "duckduckgo" in names


def test_build_queries_cross_product() -> None:
    qs = ws.build_queries(_profile())
    # 1 query × 1 location × N ATS hosts.
    assert len(qs) == len(ws.ATS_HOSTS)


def test_is_ats_host_true_and_false() -> None:
    assert ws._is_ats_host("https://boards.greenhouse.io/x/jobs/1")
    assert not ws._is_ats_host("https://random.com")


def test_is_ats_host_handles_bad_url() -> None:
    # urlparse won't actually raise for these; the function only matches against ATS_HOSTS.
    assert not ws._is_ats_host("")


# ---------------------------------------------------------------------------
# run_websearch
# ---------------------------------------------------------------------------


def test_run_websearch_zero_cap(db: sqlite3.Connection) -> None:
    p = _profile(queries_per_day=0)
    assert ws.run_websearch(p, conn=db) == (0, 0)


def test_run_websearch_inserts_ats_host(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(providers=["tavily"], queries_per_day=1)

    class _FakeProvider:
        name = "fake"

        def search(self, q: str, max_results: int = 20) -> list[dict[str, Any]]:
            return [{"url": "https://boards.greenhouse.io/acme/jobs/1", "title": "Eng", "snippet": "s"}]

    monkeypatch.setattr(ws, "build_chain", lambda providers: [_FakeProvider()])
    new, _dup = ws.run_websearch(p, conn=db)
    assert new >= 1
    row = db.execute("SELECT site FROM jobs WHERE url=?", ("https://boards.greenhouse.io/acme/jobs/1",)).fetchone()
    assert "greenhouse" in (row["site"] or "")


def test_run_websearch_browser_fallback_when_empty(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(providers=["tavily"], queries_per_day=1)

    class _Empty:
        name = "tavily"

        def search(self, q: str, max_results: int = 20) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(ws, "build_chain", lambda providers: [_Empty()])

    class _Browser:
        name = "browser"

        def __init__(self, **kw: Any) -> None:
            pass

        def search(self, q: str, max_results: int = 20) -> list[dict[str, Any]]:
            return [{"url": "https://example.com/job/1", "title": "Eng", "snippet": "s"}]

    monkeypatch.setattr(ws, "BrowserSearchProvider", _Browser)
    new, _dup = ws.run_websearch(p, conn=db)
    assert new >= 1


def test_run_websearch_provider_exception_skips(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(providers=["tavily"], queries_per_day=1)

    class _Bad:
        name = "tavily"

        def search(self, q: str, max_results: int = 20) -> list[dict[str, Any]]:
            raise RuntimeError("nope")

    class _Browser:
        name = "browser"

        def __init__(self, **kw: Any) -> None:
            pass

        def search(self, q: str, max_results: int = 20) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr(ws, "build_chain", lambda providers: [_Bad()])
    monkeypatch.setattr(ws, "BrowserSearchProvider", _Browser)
    new, dup = ws.run_websearch(p, conn=db)
    assert (new, dup) == (0, 0)
