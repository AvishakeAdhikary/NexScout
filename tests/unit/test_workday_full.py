"""Tests for ``discovery.workday`` — paginated search + detail fetch."""

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
from nexscout.discovery import workday as wd


def _profile(proxy: str | None = None) -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"},
            "search": {
                "queries": [{"q": "engineer", "tier": 1}],
                "workday_max_tier": 2,
            },
            "proxy": proxy,
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "x.sqlite")
    yield conn
    conn.close()


def test_strip_html() -> None:
    out = wd._strip_html("<p>Hello&nbsp;<b>world</b></p>")
    assert "Hello world" in out


def test_strip_html_empty() -> None:
    assert wd._strip_html("") == ""


def test_strip_html_newline_collapse() -> None:
    out = wd._strip_html("a\n\n\n\nb")
    assert "a\n\nb" in out


def test_load_employers_packaged_fallback() -> None:
    employers = wd.load_employers()
    assert isinstance(employers, dict)


def test_load_employers_yaml_path(tmp_path: Path) -> None:
    p = tmp_path / "emp.yaml"
    p.write_text(
        "employers:\n  acme:\n    name: Acme\n    base_url: https://acme.wd1.myworkdayjobs.com\n"
        "    tenant: acme\n    site_id: acme\n",
        encoding="utf-8",
    )
    out = wd.load_employers(p)
    assert out["acme"]["name"] == "Acme"


def test_load_employers_invalid_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "emp.yaml"
    p.write_text("employers: not-a-dict", encoding="utf-8")
    assert wd.load_employers(p) == {}


def test_build_client_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(proxy=None)
    with wd._build_client(p) as c:
        assert c is not None


def test_build_client_with_proxy_pair() -> None:
    """``host:port`` proxy spec."""
    p = _profile(proxy="proxy.host:8080")
    with wd._build_client(p) as c:
        assert c is not None


def test_build_client_with_proxy_quad() -> None:
    """``host:port:user:pass`` proxy spec."""
    p = _profile(proxy="proxy.host:8080:u:pw")
    with wd._build_client(p) as c:
        assert c is not None


def test_search_page_calls_post() -> None:
    client = MagicMock()
    client.post.return_value.json.return_value = {"jobPostings": []}
    out = wd._search_page(client, base_url="https://x.com/", tenant="t", site_id="s", query="eng", offset=0)
    assert out == {"jobPostings": []}
    client.post.assert_called_once()


def test_fetch_detail_missing_path() -> None:
    assert wd._fetch_detail(MagicMock(), base_url="x", tenant="t", site_id="s", external_path="") is None


def test_fetch_detail_handles_http_error() -> None:
    client = MagicMock()
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPError("400")
    client.get.return_value = response
    out = wd._fetch_detail(client, base_url="x", tenant="t", site_id="s", external_path="/job/1")
    assert out is None


def test_fetch_detail_success() -> None:
    client = MagicMock()
    client.get.return_value.json.return_value = {"jobPostingInfo": {"title": "X"}}
    out = wd._fetch_detail(client, base_url="https://x.com/", tenant="t", site_id="s", external_path="/job/1")
    assert out["jobPostingInfo"]["title"] == "X"


def test_run_workday_empty_employers(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wd, "load_employers", lambda *a, **kw: {})
    new, dup = wd.run_workday(_profile(), conn=db)
    assert (new, dup) == (0, 0)


def test_run_workday_no_eligible_queries(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile()
    p.search.queries = []
    monkeypatch.setattr(wd, "load_employers", lambda *a, **kw: {"acme": {"name": "Acme"}})
    new, dup = wd.run_workday(p, conn=db)
    assert (new, dup) == (0, 0)


def test_run_workday_paginates_and_terminates(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate three pages, terminating at ``total``."""
    monkeypatch.setattr(
        wd,
        "load_employers",
        lambda *a, **kw: {
            "acme": {
                "name": "Acme",
                "base_url": "https://acme.wd1.myworkdayjobs.com",
                "tenant": "acme",
                "site_id": "acme",
            }
        },
    )
    page_calls: list[int] = []

    def _fake_search_page(
        client: Any, *, base_url: str, tenant: str, site_id: str, query: str, offset: int
    ) -> dict[str, Any]:
        page_calls.append(offset)
        return {
            "jobPostings": [{"externalPath": f"/jobs/{offset}", "title": f"Eng-{offset}", "locationsText": "Remote"}],
            "total": 1,
        }

    monkeypatch.setattr(wd, "_search_page", _fake_search_page)
    monkeypatch.setattr(
        wd,
        "_fetch_detail",
        lambda client, **kw: {"jobPostingInfo": {"jobDescription": "<p>desc</p>", "externalUrl": "https://x.com/1"}},
    )
    monkeypatch.setattr(wd.time, "sleep", lambda s: None)
    new, _dup = wd.run_workday(_profile(), conn=db)
    assert new == 1
    # Only one page fetched because total=1.
    assert page_calls == [0]


def test_run_workday_http_error_breaks_pagination(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        wd,
        "load_employers",
        lambda *a, **kw: {
            "acme": {
                "name": "Acme",
                "base_url": "https://acme.wd1.myworkdayjobs.com",
                "tenant": "acme",
                "site_id": "acme",
            }
        },
    )

    def _bad(*a: Any, **kw: Any) -> Any:
        raise httpx.HTTPError("500")

    monkeypatch.setattr(wd, "_search_page", _bad)
    new, _dup = wd.run_workday(_profile(), conn=db)
    assert new == 0


def test_run_workday_skips_employers_missing_fields(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """An employer missing base_url/tenant/site_id is skipped silently."""
    monkeypatch.setattr(
        wd,
        "load_employers",
        lambda *a, **kw: {"bad": {"name": "Bad"}},
    )
    new, dup = wd.run_workday(_profile(), conn=db)
    assert (new, dup) == (0, 0)


def test_run_workday_rejects_off_location(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """A job in a rejected location is skipped without inserting."""
    monkeypatch.setattr(
        wd,
        "load_employers",
        lambda *a, **kw: {
            "acme": {
                "name": "Acme",
                "base_url": "https://acme.wd1.myworkdayjobs.com",
                "tenant": "acme",
                "site_id": "acme",
            }
        },
    )

    def _fake_search_page(*a: Any, **kw: Any) -> dict[str, Any]:
        return {
            "jobPostings": [{"externalPath": "/jobs/1", "title": "Eng", "locationsText": "Berlin"}],
            "total": 1,
        }

    monkeypatch.setattr(wd, "_search_page", _fake_search_page)
    monkeypatch.setattr(wd.time, "sleep", lambda s: None)
    p = _profile()
    p.search.location_reject_non_remote = ["Berlin"]
    new, _dup = wd.run_workday(p, conn=db)
    assert new == 0
