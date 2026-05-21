"""Full coverage for ``enrichment.detail``."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.database import init_db
from nexscout.enrichment import detail as ed


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "x.sqlite")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# HTTP error helpers
# ---------------------------------------------------------------------------


def test_is_permanent_http_error() -> None:
    assert ed.is_permanent_http_error(404)
    assert ed.is_permanent_http_error(410)
    assert ed.is_permanent_http_error(451)
    assert not ed.is_permanent_http_error(500)


def test_is_transient_http_error() -> None:
    for code in (408, 429, 500, 502, 503, 504):
        assert ed.is_transient_http_error(code)
    assert not ed.is_transient_http_error(404)


# ---------------------------------------------------------------------------
# HTML cleaning
# ---------------------------------------------------------------------------


def test_clean_description_html_empty() -> None:
    assert ed.clean_description_html("") == ""


def test_clean_description_html_br_li_p() -> None:
    html = "<p>Intro<br>line2</p><ul><li>A</li><li>B</li></ul>"
    out = ed.clean_description_html(html)
    assert "Intro" in out
    assert "- A" in out
    assert "- B" in out


def test_clean_description_html_no_blocks_uses_plain_text() -> None:
    out = ed.clean_description_html("<span>hello world</span>")
    assert "hello world" in out


# ---------------------------------------------------------------------------
# JSON-LD parsing
# ---------------------------------------------------------------------------


def test_parse_jsonld_blocks_returns_objects() -> None:
    html = (
        '<html><script type="application/ld+json">{"@type":"JobPosting","title":"x"}</script>'
        '<script type="application/ld+json">[{"@type":"JobPosting","title":"y"}]</script></html>'
    )
    out = ed.parse_jsonld_blocks(html)
    assert any(isinstance(o, dict) and o.get("title") == "x" for o in out)


def test_parse_jsonld_blocks_handles_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    html = '<script type="application/ld+json">not-json</script>'
    # extract_json fallback returns None → skipped without raising
    out = ed.parse_jsonld_blocks(html)
    assert out == []


def test_extract_posting_from_jsonld_simple() -> None:
    blocks = [{"@type": "JobPosting", "title": "x"}]
    p = ed.extract_posting_from_jsonld(blocks)
    assert p and p["title"] == "x"


def test_extract_posting_from_jsonld_graph_recursion() -> None:
    blocks = [
        {"@graph": [{"@type": "Other"}, {"@type": "JobPosting", "title": "x"}]},
    ]
    p = ed.extract_posting_from_jsonld(blocks)
    assert p and p["title"] == "x"


def test_extract_posting_from_jsonld_none() -> None:
    assert ed.extract_posting_from_jsonld([{"@type": "Organisation"}]) is None


def test_extract_apply_url_from_posting_direct() -> None:
    out = ed.extract_apply_url_from_posting({"directApply": True, "url": "https://x.com/apply"})
    assert out == "https://x.com/apply"


def test_extract_apply_url_from_posting_indirect_contact() -> None:
    out = ed.extract_apply_url_from_posting(
        {"directApply": False, "applicationContact": {"url": "https://x.com/apply2"}}
    )
    assert out == "https://x.com/apply2"


def test_extract_apply_url_from_posting_none() -> None:
    assert ed.extract_apply_url_from_posting({"directApply": False}) is None


# ---------------------------------------------------------------------------
# Tier 1 — JSON-LD
# ---------------------------------------------------------------------------


def test_tier1_jsonld_accepts_long_description() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type":"JobPosting","title":"x","description":"' + "a" * 60 + '","url":"https://x.com/apply"}'
        "</script>"
    )
    res = ed.tier1_jsonld(html)
    assert res and res.tier == "json_ld"


def test_tier1_jsonld_too_short() -> None:
    html = '<script type="application/ld+json">{"@type":"JobPosting","description":"short"}</script>'
    assert ed.tier1_jsonld(html) is None


def test_tier1_jsonld_no_posting() -> None:
    html = '<script type="application/ld+json">{"@type":"Organization"}</script>'
    assert ed.tier1_jsonld(html) is None


def test_tier1_jsonld_no_blocks() -> None:
    assert ed.tier1_jsonld("<html/>") is None


def test_tier1_jsonld_description_html_cleaned() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type":"JobPosting","description":"<p>' + "a" * 60 + '</p>"}'
        "</script>"
    )
    res = ed.tier1_jsonld(html)
    assert res and "<p>" not in res.full_description


# ---------------------------------------------------------------------------
# Tier 2 — CSS selectors
# ---------------------------------------------------------------------------


def test_tier2_css_accepts_long_match() -> None:
    html = (
        '<html><body><div id="job-description">' + "<p>x</p>" * 30 + "</div>"
        '<a href="https://x.com/apply" class="apply-btn">Apply</a></body></html>'
    )
    res = ed.tier2_css(html)
    assert res and res.tier == "css"
    assert res.application_url == "https://x.com/apply"


def test_tier2_css_no_match() -> None:
    assert ed.tier2_css("<html/>") is None


# ---------------------------------------------------------------------------
# Tier 3 — LLM
# ---------------------------------------------------------------------------


def test_tier3_llm_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class _R:
        def ask(self, task: str, messages: Any, **kw: Any) -> str:
            return '{"full_description":"This is a long enough description","application_url":"https://x.com/apply","cover_required":false}'

    res = ed.tier3_llm(router=_R(), url="https://x.com", title="t", html="<html><main>Hi</main></html>")  # type: ignore[arg-type]
    assert res and res.tier == "llm"


def test_tier3_llm_empty_desc() -> None:
    class _R:
        def ask(self, task: str, messages: Any, **kw: Any) -> str:
            return '{"full_description":"","application_url":null}'

    assert ed.tier3_llm(router=_R(), url="x", title="t", html="<html/>") is None  # type: ignore[arg-type]


def test_tier3_llm_router_failure() -> None:
    class _R:
        def ask(self, *a: Any, **kw: Any) -> str:
            raise RuntimeError("provider")

    assert ed.tier3_llm(router=_R(), url="x", title="t", html="<html/>") is None  # type: ignore[arg-type]


def test_tier3_llm_unparseable() -> None:
    class _R:
        def ask(self, *a: Any, **kw: Any) -> str:
            return "not json"

    assert ed.tier3_llm(router=_R(), url="x", title="t", html="<html/>") is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# extract_main_content
# ---------------------------------------------------------------------------


def test_extract_main_content_picks_main_when_long() -> None:
    html = "<html><body><main>" + ("x" * 250) + "</main></body></html>"
    out = ed.extract_main_content(html)
    assert "main" in out.lower()


def test_extract_main_content_fallback_to_body() -> None:
    html = "<html><body><nav>links</nav><p>" + "x" * 250 + "</p></body></html>"
    out = ed.extract_main_content(html)
    assert "<nav" not in out


def test_extract_main_content_no_body() -> None:
    out = ed.extract_main_content("<p>short text</p>")
    assert "<p>" in out or "short text" in out


# ---------------------------------------------------------------------------
# enrich_html cascade
# ---------------------------------------------------------------------------


def test_enrich_html_empty_returns_none() -> None:
    assert ed.enrich_html("", url="x", title="t") is None


def test_enrich_html_tier1_first() -> None:
    html = (
        '<script type="application/ld+json">'
        '{"@type":"JobPosting","description":"' + "a" * 60 + '"}'
        "</script>"
    )
    res = ed.enrich_html(html, url="x", title="t")
    assert res and res.tier == "json_ld"


def test_enrich_html_no_router_returns_none_after_t1_t2() -> None:
    assert ed.enrich_html("<html><body><p>x</p></body></html>", url="x", title="t") is None


# ---------------------------------------------------------------------------
# resolve_relative_url
# ---------------------------------------------------------------------------


def test_resolve_relative_url_absolute_passthrough() -> None:
    assert ed.resolve_relative_url("https://x.com", "site") == "https://x.com"


def test_resolve_relative_url_with_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed, "_BASE_URL_CACHE", None)
    monkeypatch.setattr(ed, "_load_base_urls", lambda: {"mysite": "https://x.com/"})
    assert ed.resolve_relative_url("/jobs/1", "mysite") == "https://x.com/jobs/1"


def test_resolve_relative_url_no_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed, "_BASE_URL_CACHE", None)
    monkeypatch.setattr(ed, "_load_base_urls", lambda: {})
    assert ed.resolve_relative_url("/x", "unknown") == "/x"


def test_resolve_relative_url_empty() -> None:
    assert ed.resolve_relative_url("", "site") == ""


def test_load_base_urls_finds_packaged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed, "_BASE_URL_CACHE", None)
    out = ed._load_base_urls()
    assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# site_delay
# ---------------------------------------------------------------------------


def test_site_delay_known() -> None:
    assert ed.site_delay("RemoteOK") == 3.0


def test_site_delay_unknown() -> None:
    assert ed.site_delay("unknown") == ed.DEFAULT_DELAY
    assert ed.site_delay(None) == ed.DEFAULT_DELAY


# ---------------------------------------------------------------------------
# persist helpers
# ---------------------------------------------------------------------------


def test_persist_enrichment(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO jobs (url, title) VALUES (?, ?)", ("https://x.com/1", "Eng"))
    ed.persist_enrichment(
        db,
        "https://x.com/1",
        ed.EnrichmentResult(
            full_description="hello",
            application_url="https://x.com/apply",
            cover_required=True,
            tier="json_ld",
        ),
    )
    row = db.execute(
        "SELECT full_description, application_url, cover_required FROM jobs WHERE url=?",
        ("https://x.com/1",),
    ).fetchone()
    assert row["full_description"] == "hello"
    assert row["cover_required"] == 1


def test_persist_enrichment_error(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO jobs (url, title) VALUES (?, ?)", ("https://x.com/1", "Eng"))
    ed.persist_enrichment_error(db, "https://x.com/1", "404")
    row = db.execute("SELECT detail_error FROM jobs WHERE url=?", ("https://x.com/1",)).fetchone()
    assert row["detail_error"] == "404"


# ---------------------------------------------------------------------------
# enrich_row
# ---------------------------------------------------------------------------


def test_enrich_row_drives_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed.time, "sleep", lambda s: None)

    class _Drv:
        page_source = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","description":"' + "a" * 60 + '"}'
            "</script>"
        )

        def get(self, url: str) -> None:
            return None

        def quit(self) -> None:
            return None

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return _Drv()

    out = ed.enrich_row(row={"url": "https://x.com/job", "title": "t", "site": "RemoteOK"}, factory=_Fac())
    assert out and out.tier == "json_ld"


def test_enrich_row_driver_quit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ed.time, "sleep", lambda s: None)

    class _Drv:
        page_source = "<html/>"

        def get(self, url: str) -> None:
            return None

        def quit(self) -> None:
            raise RuntimeError("nope")

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return _Drv()

    out = ed.enrich_row(row={"url": "https://x.com/job", "title": "t", "site": ""}, factory=_Fac())
    # No tier matched but the function returned gracefully.
    assert out is None
