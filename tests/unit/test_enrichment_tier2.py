"""Tier 2 — deterministic CSS selectors accept descriptions >= 100 chars."""

from __future__ import annotations

from nexscout.enrichment.detail import APPLY_SELECTORS, DESCRIPTION_SELECTORS, tier2_css


def test_apply_selectors_are_verbatim_count() -> None:
    # Sanity check that the verbatim §9 arrays did not silently shrink.
    assert len(APPLY_SELECTORS) == 13
    assert len(DESCRIPTION_SELECTORS) == 23


def test_tier2_picks_up_descriptive_div() -> None:
    long_body = "Lorem ipsum " * 30
    html = f"""<html><body>
        <div id="job-description"><p>{long_body}</p></div>
        <a href="/apply/123" class="apply-btn">Apply now</a>
    </body></html>"""
    result = tier2_css(html)
    assert result is not None
    assert len(result.full_description) >= 100
    assert result.application_url == "/apply/123"


def test_tier2_rejects_short_description() -> None:
    html = """<html><body>
        <div id="job-description">too short</div>
    </body></html>"""
    assert tier2_css(html) is None


def test_tier2_falls_through_unknown_layout() -> None:
    html = "<html><body><div class='random'>nope</div></body></html>"
    assert tier2_css(html) is None
