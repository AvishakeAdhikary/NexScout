"""Tier 1 — JSON-LD parsing accepts a JobPosting with description >= 50 chars."""

from __future__ import annotations

from nexscout.enrichment.detail import (
    extract_apply_url_from_posting,
    extract_posting_from_jsonld,
    parse_jsonld_blocks,
    tier1_jsonld,
)

_HTML_TEMPLATE = """<html><head>
<script type="application/ld+json">
{json}
</script>
</head><body><h1>job</h1></body></html>"""


def _wrap(payload: str) -> str:
    return _HTML_TEMPLATE.replace("{json}", payload)


def test_tier1_accepts_long_description() -> None:
    desc = "This is a long enough description with plenty of meaningful content to exceed fifty characters."
    payload = (
        '{"@type":"JobPosting",'
        f'"description":"{desc}",'
        '"directApply":true,'
        '"url":"https://example.com/apply/123"}'
    )
    result = tier1_jsonld(_wrap(payload))
    assert result is not None
    assert result.tier == "json_ld"
    assert result.application_url == "https://example.com/apply/123"
    assert "long enough description" in result.full_description


def test_tier1_rejects_short_description() -> None:
    payload = '{"@type":"JobPosting","description":"too short"}'
    assert tier1_jsonld(_wrap(payload)) is None


def test_tier1_walks_graph() -> None:
    payload = (
        '{"@context":"https://schema.org","@graph":['
        '{"@type":"Organization","name":"Acme"},'
        '{"@type":"JobPosting","description":"Detailed multi-line description with lots of helpful relevant content.",'
        '"url":"https://example.com/job"}'
        "]}"
    )
    posting = extract_posting_from_jsonld(parse_jsonld_blocks(_wrap(payload)))
    assert posting is not None
    assert posting["@type"] == "JobPosting"


def test_tier1_html_description_is_cleaned() -> None:
    payload = (
        '{"@type":"JobPosting",'
        '"description":"<p>First paragraph that adds enough length to satisfy the fifty character minimum check.</p>'
        "<ul><li>One</li><li>Two</li></ul>"
        '<p>Second paragraph here.</p>",'
        '"url":"https://example.com/apply"}'
    )
    result = tier1_jsonld(_wrap(payload))
    assert result is not None
    assert "- One" in result.full_description
    assert "- Two" in result.full_description
    assert "First paragraph" in result.full_description


def test_apply_url_prefers_direct_then_contact_then_url() -> None:
    posting = {
        "directApply": False,
        "applicationContact": {"url": "https://contact/apply"},
        "url": "https://canonical",
    }
    assert extract_apply_url_from_posting(posting) == "https://contact/apply"
    posting["directApply"] = True
    assert extract_apply_url_from_posting(posting) == "https://canonical"
