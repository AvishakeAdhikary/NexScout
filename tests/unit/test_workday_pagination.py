"""Workday pagination & insert behaviour using a mocked httpx transport."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.discovery import workday as wd


@pytest.fixture
def example_profile(tmp_path: Path) -> Iterator[Profile]:
    src = Path(__file__).resolve().parents[2] / "examples" / "profile.example.yaml"
    dest = tmp_path / "profile.yaml"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    yield Profile.from_path(dest)


def _make_handler(pages: list[list[dict]]) -> httpx.MockTransport:
    """Return a MockTransport that serves a single tenant's search + details."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and "/jobs" in url and "/wday/cxs/" in url:
            body = request.read().decode()
            offset = 0
            for line in body.split(","):
                if '"offset"' in line:
                    try:
                        offset = int(line.split(":", 1)[1].strip().rstrip("}"))
                    except (ValueError, IndexError):
                        offset = 0
            page_idx = offset // wd.PAGE_SIZE
            if page_idx >= len(pages):
                return httpx.Response(200, json={"jobPostings": [], "total": sum(len(p) for p in pages)})
            return httpx.Response(
                200,
                json={
                    "jobPostings": pages[page_idx],
                    "total": sum(len(p) for p in pages),
                },
            )
        if request.method == "GET" and "/wday/cxs/" in url:
            return httpx.Response(
                200,
                json={
                    "jobPostingInfo": {
                        "title": "Detailed Title",
                        "jobDescription": "<p>Hello <b>world</b></p>",
                        "externalUrl": str(request.url),
                    }
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _build_client(profile: Profile, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(transport=transport, timeout=timeout, headers=wd.HEADERS)


transport: httpx.MockTransport  # populated in tests


def test_workday_paginates_until_total(
    monkeypatch: pytest.MonkeyPatch, example_profile: Profile, tmp_path: Path
) -> None:
    pages = [
        [{"title": f"J{i}", "externalPath": f"/job/{i}", "locationsText": "Remote"} for i in range(wd.PAGE_SIZE)],
        [{"title": "J20", "externalPath": "/job/20", "locationsText": "Remote"}],
    ]
    global transport
    transport = _make_handler(pages)
    monkeypatch.setattr(wd, "_build_client", _build_client)

    # Single-employer stub.
    single = {
        "td": {
            "name": "TD Bank",
            "tenant": "td",
            "site_id": "TD_Bank_Careers",
            "base_url": "https://td.example.com",
        }
    }
    monkeypatch.setattr(wd, "load_employers", lambda *_a, **_kw: single)
    monkeypatch.setattr(wd, "ship_default_employers", lambda *_a, **_kw: tmp_path / "employers.yaml")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    example_profile.search.queries = [example_profile.search.queries[0]]
    example_profile.search.workday_max_tier = 5

    conn = init_db(tmp_path / "j.sqlite")
    new, dup = wd.run_workday(example_profile, conn=conn, max_pages=10)
    assert new == 21
    assert dup == 0


def test_workday_stop_when_total_reached(
    monkeypatch: pytest.MonkeyPatch, example_profile: Profile, tmp_path: Path
) -> None:
    pages = [[{"title": "Only", "externalPath": "/job/x", "locationsText": "Remote"}]]
    global transport
    transport = _make_handler(pages)
    monkeypatch.setattr(wd, "_build_client", _build_client)
    monkeypatch.setattr(
        wd,
        "load_employers",
        lambda *_a, **_kw: {
            "td": {
                "name": "TD Bank",
                "tenant": "td",
                "site_id": "TD_Bank_Careers",
                "base_url": "https://td.example.com",
            }
        },
    )
    monkeypatch.setattr(wd, "ship_default_employers", lambda *_a, **_kw: tmp_path / "employers.yaml")
    monkeypatch.setattr("time.sleep", lambda *_a, **_kw: None)

    example_profile.search.queries = [example_profile.search.queries[0]]
    example_profile.search.workday_max_tier = 5

    conn = init_db(tmp_path / "j.sqlite")
    new, _dup = wd.run_workday(example_profile, conn=conn, max_pages=10)
    assert new == 1
