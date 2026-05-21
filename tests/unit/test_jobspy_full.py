"""Tests for ``discovery.jobspy`` — engine, retry logic, salary formatting."""

from __future__ import annotations

import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.discovery import jobspy as js


def _profile(boards: list[str] | None = None) -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"},
            "search": {
                "queries": [{"q": "engineer", "tier": 1}],
                "locations": [{"label": "Remote", "q": "Remote", "remote": True}],
                "boards": {"jobspy": boards if boards is not None else ["indeed"]},
            },
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "x.sqlite")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# format_salary
# ---------------------------------------------------------------------------


def test_format_salary_range() -> None:
    out = js._format_salary({"min_amount": 100000, "max_amount": 150000})
    assert out == "$100,000-$150,000/yr"


def test_format_salary_only_min() -> None:
    out = js._format_salary({"min_amount": 100000})
    assert out == "$100,000/yr"


def test_format_salary_only_max() -> None:
    out = js._format_salary({"max_amount": 200000})
    assert out == "$200,000/yr"


def test_format_salary_none() -> None:
    assert js._format_salary({}) is None


def test_format_salary_bad_type() -> None:
    assert js._format_salary({"min_amount": "junk", "max_amount": "junk"}) is None


def test_format_salary_alternate_keys() -> None:
    out = js._format_salary({"salary_min": 50000, "salary_max": 70000, "salary_currency": "€", "salary_interval": "mo"})
    assert "€50,000-€70,000/mo" in out


# ---------------------------------------------------------------------------
# location_passes
# ---------------------------------------------------------------------------


def test_location_passes_empty() -> None:
    assert js.location_passes("")
    assert js.location_passes(None)


def test_location_passes_remote_signal() -> None:
    assert js.location_passes("Remote — Anywhere")
    assert js.location_passes("Work from home")


def test_location_passes_accept_list() -> None:
    assert js.location_passes("Toronto, ON", accept=["Toronto"])
    assert not js.location_passes("New York", accept=["Toronto"], reject_non_remote=["New York"])


def test_location_passes_reject_list() -> None:
    assert not js.location_passes("Berlin, DE", reject_non_remote=["Berlin"])


# ---------------------------------------------------------------------------
# _is_retryable
# ---------------------------------------------------------------------------


def test_is_retryable_matches() -> None:
    assert js._is_retryable(RuntimeError("timeout reading"))
    assert js._is_retryable(RuntimeError("connection refused"))
    assert js._is_retryable(RuntimeError("HTTP 429 from server"))


def test_is_retryable_no_match() -> None:
    assert not js._is_retryable(RuntimeError("something else"))


# ---------------------------------------------------------------------------
# _df_iter
# ---------------------------------------------------------------------------


def test_df_iter_none() -> None:
    assert js._df_iter(None) == []


def test_df_iter_dataframe_like() -> None:
    class _Fake:
        def fillna(self, value: str) -> Any:
            return self

        def to_dict(self, orient: str) -> list[dict[str, Any]]:
            return [{"job_url": "x"}]

    assert js._df_iter(_Fake()) == [{"job_url": "x"}]


def test_df_iter_list_passthrough() -> None:
    assert js._df_iter([{"a": 1}]) == [{"a": 1}]


# ---------------------------------------------------------------------------
# _build_rows
# ---------------------------------------------------------------------------


def test_build_rows_dedups_no_url() -> None:
    out = js._build_rows([{"title": "x"}], profile=_profile(), discovered_at="2025")
    assert out == []


def test_build_rows_filters_location() -> None:
    p = _profile()
    p.search.location_reject_non_remote = ["Berlin"]
    out = js._build_rows(
        [{"job_url": "http://x", "location": "Berlin, DE", "description": "y"}],
        profile=p,
        discovered_at="2025",
    )
    assert out == []


def test_build_rows_full_description_passthrough() -> None:
    long_desc = "a" * 500
    out = js._build_rows(
        [{"job_url": "http://x", "title": "Eng", "description": long_desc}],
        profile=_profile(),
        discovered_at="2025",
    )
    assert out[0]["full_description"] == long_desc


def test_build_rows_short_description_no_full() -> None:
    out = js._build_rows(
        [{"job_url": "http://x", "title": "Eng", "description": "short"}],
        profile=_profile(),
        discovered_at="2025",
    )
    assert "full_description" not in out[0]


# ---------------------------------------------------------------------------
# _import_scrape_jobs
# ---------------------------------------------------------------------------


def test_import_scrape_jobs_via_jobspy(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_mod = ModuleType("jobspy")
    fake_mod.scrape_jobs = lambda *a, **kw: "ok"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "jobspy", fake_mod)
    out = js._import_scrape_jobs()
    assert callable(out)


def test_import_scrape_jobs_via_python_jobspy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jobspy", None)  # type: ignore[arg-type]
    fake_mod = ModuleType("python_jobspy")
    fake_mod.scrape_jobs = lambda *a, **kw: "ok2"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "python_jobspy", fake_mod)
    out = js._import_scrape_jobs()
    assert callable(out)


def test_import_scrape_jobs_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "jobspy", None)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "python_jobspy", None)  # type: ignore[arg-type]
    with pytest.raises(ImportError):
        js._import_scrape_jobs()


# ---------------------------------------------------------------------------
# _scrape_with_retry
# ---------------------------------------------------------------------------


def test_scrape_with_retry_returns_first_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _scrape(*a: Any, **kw: Any) -> str:
        calls["n"] += 1
        return "ok"

    monkeypatch.setattr(js, "_import_scrape_jobs", lambda: _scrape)
    assert js._scrape_with_retry(["indeed"]) == "ok"
    assert calls["n"] == 1


def test_scrape_with_retry_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _scrape(*a: Any, **kw: Any) -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("connection reset")
        return "ok"

    monkeypatch.setattr(js, "_import_scrape_jobs", lambda: _scrape)
    monkeypatch.setattr(js.time, "sleep", lambda s: None)
    assert js._scrape_with_retry(["indeed"]) == "ok"
    assert calls["n"] == 2


def test_scrape_with_retry_non_retryable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _scrape(*a: Any, **kw: Any) -> None:
        raise RuntimeError("unrelated bug")

    monkeypatch.setattr(js, "_import_scrape_jobs", lambda: _scrape)
    monkeypatch.setattr(js.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        js._scrape_with_retry(["indeed"])


# ---------------------------------------------------------------------------
# run_jobspy
# ---------------------------------------------------------------------------


def test_run_jobspy_no_boards_returns_zero(db: sqlite3.Connection) -> None:
    p = _profile(boards=[])
    new, dup = js.run_jobspy(p, conn=db)
    assert (new, dup) == (0, 0)


def test_run_jobspy_inserts_rows(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(boards=["indeed", "linkedin"])

    def _fake_scrape(*a: Any, **kw: Any) -> Any:
        return [
            {
                "job_url": "https://x.com/jobs/1",
                "title": "Eng",
                "location": "Remote",
                "description": "Long description " * 30,
                "site": "indeed",
            }
        ]

    monkeypatch.setattr(js, "_scrape_with_retry", _fake_scrape)
    new, _dup = js.run_jobspy(p, conn=db)
    assert new == 1
    row = db.execute("SELECT title FROM jobs WHERE url=?", ("https://x.com/jobs/1",)).fetchone()
    assert row["title"] == "Eng"


def test_run_jobspy_glassdoor_split(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(boards=["indeed", "glassdoor"])
    captured: list[list[str]] = []

    def _fake_scrape(boards: list[str], **kw: Any) -> Any:
        captured.append(boards)
        return []

    monkeypatch.setattr(js, "_scrape_with_retry", _fake_scrape)
    js.run_jobspy(p, conn=db)
    # First call: non-glassdoor boards. Second: glassdoor alone.
    assert ["indeed"] in captured
    assert ["glassdoor"] in captured


def test_run_jobspy_handles_main_pull_failure(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = _profile(boards=["indeed"])

    def _bad(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("network")

    monkeypatch.setattr(js, "_scrape_with_retry", _bad)
    new, dup = js.run_jobspy(p, conn=db)
    assert (new, dup) == (0, 0)
