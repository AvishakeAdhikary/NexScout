"""Tests for ``discovery.smartextract.extract_json`` and friends."""

from __future__ import annotations

from nexscout.discovery.smartextract import (
    execute_api_response,
    execute_css_selectors,
    execute_json_ld,
    extract_json,
    resolve_path,
)


def test_extract_json_plain() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_think_tags() -> None:
    text = '<think>blah blah</think>\n{"x": 2}'
    assert extract_json(text) == {"x": 2}


def test_extract_json_strips_code_fence() -> None:
    text = '```json\n{"y": 3}\n```'
    assert extract_json(text) == {"y": 3}


def test_extract_json_balanced_in_noise() -> None:
    text = 'Here is the result:\n{"a":[1,2,3],"b":{"c":1}}\n\nThanks!'
    assert extract_json(text) == {"a": [1, 2, 3], "b": {"c": 1}}


def test_extract_json_trailing_garbage_trim() -> None:
    text = '{"a": 1}xxx'
    assert extract_json(text) == {"a": 1}


def test_extract_json_returns_none_on_failure() -> None:
    assert extract_json("not json at all") is None
    assert extract_json("") is None


def test_resolve_path_dot_and_index() -> None:
    obj = {"results": [{"hits": [{"title": "A"}, {"title": "B"}]}]}
    assert resolve_path(obj, "results[0].hits[1].title") == "B"
    assert resolve_path(obj, "results[0].hits") == [{"title": "A"}, {"title": "B"}]
    assert resolve_path(obj, "missing") is None


def test_execute_json_ld_handles_graph() -> None:
    entries = [
        {
            "@graph": [
                {"@type": "JobPosting", "title": "SWE", "description": "build stuff", "url": "https://x/y"},
                {"@type": "Other"},
            ]
        }
    ]
    out = execute_json_ld(entries, {"title": "title", "description": "description", "url": "url"})
    assert len(out) == 1
    assert out[0]["title"] == "SWE"


def test_execute_api_response_walks_items_path() -> None:
    responses = [
        {
            "url": "https://example.com/api/jobs",
            "body": {"results": [{"hits": [{"Title": "X", "_source": {"loc": "Remote"}}]}]},
        }
    ]
    extraction = {
        "url_pattern": "/api/jobs",
        "items_path": "results[0].hits",
        "title": "Title",
        "location": "_source.loc",
    }
    out = execute_api_response(responses, extraction)
    assert out == [{"title": "X", "salary": None, "description": None, "location": "Remote", "url": None}]


def test_execute_css_selectors_basic() -> None:
    html = (
        "<html><body>"
        "<article class='job'><h2>Senior Dev</h2><a href='/jobs/1'>apply</a></article>"
        "<article class='job'><h2>Junior Dev</h2><a href='/jobs/2'>apply</a></article>"
        "</body></html>"
    )
    selectors = {"job_card": "article.job", "title": "h2", "url": "a"}
    out = execute_css_selectors(html, selectors, base_url="https://x.com")
    titles = [r["title"] for r in out]
    assert titles == ["Senior Dev", "Junior Dev"]
    assert out[0]["url"] == "https://x.com/jobs/1"
