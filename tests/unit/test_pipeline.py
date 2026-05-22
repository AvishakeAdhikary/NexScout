"""Tests for ``nexscout.pipeline``.

Exercises every public stage (discover, enrich, score, tailor, cover, render)
plus the streaming entry point and ``parse_resume_txt`` round-trip.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nexscout import pipeline
from nexscout.core.database import init_db
from nexscout.core.profile import Profile


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "search": {"min_score": 7},
            "apply": {"max_attempts": 3, "always_cover_letter": False},
        }
    )


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = init_db(tmp_path / "test.sqlite")
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# parse_resume_txt round-trip
# ---------------------------------------------------------------------------


def test_parse_resume_txt_empty_returns_skeleton() -> None:
    data = pipeline.parse_resume_txt("")
    assert data["title"] == ""
    assert data["summary"] == ""
    assert data["skills"] == {}
    assert data["experience"] == []


def test_parse_resume_txt_roundtrip() -> None:
    text = (
        "Jane Q. Public\n"
        "Staff Engineer\n"
        "jane@x.com\n"
        "\n"
        "SUMMARY\n"
        "Experienced engineer.\n"
        "Delivered impact at Acme.\n"
        "\n"
        "TECHNICAL SKILLS\n"
        "Languages: Python, Go\n"
        "Infra: Docker, Kubernetes\n"
        "\n"
        "EXPERIENCE\n"
        "Acme Corp\n"
        "Senior Engineer (2020-)\n"
        "- Built systems\n"
        "- Shipped features\n"
        "\n"
        "PROJECTS\n"
        "Search Indexer\n"
        "- Reduced p99 by 40%\n"
        "\n"
        "EDUCATION\n"
        "BSc Computer Science\n"
    )
    data = pipeline.parse_resume_txt(text)
    assert data["title"] == "Staff Engineer"
    assert "Experienced engineer." in data["summary"]
    assert data["skills"]["Languages"] == "Python, Go"
    assert data["experience"]
    assert data["experience"][0]["header"] == "Acme Corp"
    assert "Built systems" in data["experience"][0]["bullets"]
    assert data["projects"]
    assert "BSc Computer Science" in data["education"]


def test_parse_resume_txt_multiple_experience_items() -> None:
    text = "Name\nTitle\nEXPERIENCE\nAcme\nEngineer\n- A\nGlobex\nEngineer\n- B\n"
    data = pipeline.parse_resume_txt(text)
    assert len(data["experience"]) == 2


# ---------------------------------------------------------------------------
# Discover stage — engine fan-out
# ---------------------------------------------------------------------------


def test_run_discover_stage_no_engines_available(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """When every discovery sub-module raises, run_discover_stage returns 0."""
    from nexscout.discovery import jobspy as js_mod
    from nexscout.discovery import websearch as ws_mod
    from nexscout.discovery import workday as wd_mod

    def boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("nope")

    monkeypatch.setattr(js_mod, "run_jobspy", boom)
    monkeypatch.setattr(wd_mod, "run_workday", boom)
    monkeypatch.setattr(ws_mod, "run_websearch", boom)
    out = pipeline.run_discover_stage(conn=db, profile=_profile(), router=None)
    assert out == 0


def test_run_discover_stage_aggregates_counts(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.discovery import jobspy as js_mod
    from nexscout.discovery import smartextract as se_mod
    from nexscout.discovery import websearch as ws_mod
    from nexscout.discovery import workday as wd_mod

    monkeypatch.setattr(js_mod, "run_jobspy", lambda *a, **kw: (3, 0))
    monkeypatch.setattr(wd_mod, "run_workday", lambda *a, **kw: (5, 1))
    monkeypatch.setattr(ws_mod, "run_websearch", lambda *a, **kw: (2, 0))
    monkeypatch.setattr(se_mod, "run_smartextract", lambda *a, **kw: (1, 0))

    class _Router:
        pass

    out = pipeline.run_discover_stage(conn=db, profile=_profile(), router=_Router())  # type: ignore[arg-type]
    assert out == 3 + 5 + 2 + 1


# ---------------------------------------------------------------------------
# Enrich stage
# ---------------------------------------------------------------------------


def _insert_pending(conn: sqlite3.Connection, url: str, site: str = "greenhouse") -> None:
    conn.execute(
        "INSERT INTO jobs (url, title, site, application_url) VALUES (?, ?, ?, ?)",
        (url, "Engineer", site, None),
    )


def test_run_enrich_stage_success(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_pending(db, "https://a.com/1")

    from nexscout.enrichment import detail as detail_mod

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return SimpleNamespace()

    def _enrich_row(*, row: dict[str, Any], **_kw: Any) -> Any:
        return detail_mod.EnrichmentResult(
            full_description="Long description " * 10,
            application_url=None,
            cover_required=False,
            tier="json_ld",
        )

    monkeypatch.setattr(detail_mod, "enrich_row", _enrich_row)
    n = pipeline.run_enrich_stage(conn=db, profile=_profile(), browser_factory=_Fac())
    assert n == 1
    row = db.execute("SELECT full_description FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["full_description"]


def test_run_enrich_stage_handles_none_result(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_pending(db, "https://a.com/1")

    from nexscout.enrichment import detail as detail_mod

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return SimpleNamespace()

    monkeypatch.setattr(detail_mod, "enrich_row", lambda **kw: None)
    n = pipeline.run_enrich_stage(conn=db, profile=_profile(), browser_factory=_Fac())
    assert n == 0
    row = db.execute("SELECT detail_error FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["detail_error"] == "no_extractor_succeeded"


def test_run_enrich_stage_handles_exception(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_pending(db, "https://a.com/1")

    from nexscout.enrichment import detail as detail_mod

    class _Fac:
        def make(self, *, headless: bool = True) -> Any:
            return SimpleNamespace()

    def _boom(**_kw: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(detail_mod, "enrich_row", _boom)
    n = pipeline.run_enrich_stage(conn=db, profile=_profile(), browser_factory=_Fac())
    assert n == 0
    row = db.execute("SELECT detail_error FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert "kaboom" in row["detail_error"]


def test_run_enrich_stage_skips_blocked_sites(db: sqlite3.Connection) -> None:
    _insert_pending(db, "https://a.com/1", site="glassdoor")
    n = pipeline.run_enrich_stage(conn=db, profile=_profile(), browser_factory=None)
    assert n == 0


def test_run_enrich_stage_no_factory(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    _insert_pending(db, "https://a.com/1")

    def _boom(*a: Any, **kw: Any) -> Any:
        raise RuntimeError("no Chrome")

    monkeypatch.setattr("nexscout.browser.driver.UndetectedFactory", _boom)
    n = pipeline.run_enrich_stage(conn=db, profile=_profile(), browser_factory=None)
    assert n == 0


# ---------------------------------------------------------------------------
# Score / tailor / cover stages with mock router
# ---------------------------------------------------------------------------


class _Router:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, list[Any]]] = []

    def ask(self, task: str, messages: Any, **_kw: Any) -> str:
        self.calls.append((task, list(messages)))
        return self.responses.pop(0) if self.responses else "{}"


def test_run_score_stage(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, full_description) VALUES (?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "greenhouse", "We need a backend engineer."),
    )

    def _score_job(router: Any, profile: Any, job: dict[str, Any]) -> tuple[int, str]:
        return 8, "good fit"

    monkeypatch.setattr(pipeline, "score_job", _score_job)
    n = pipeline.run_score_stage(conn=db, router=_Router([]), profile=_profile())  # type: ignore[arg-type]
    assert n == 1
    row = db.execute("SELECT fit_score FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["fit_score"] == 8


def test_run_tailor_stage_approved(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, full_description, fit_score) VALUES (?, ?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "greenhouse", "Backend role.", 9),
    )

    from nexscout.scoring.tailor import TailorResult

    def _tailor(**_kw: Any) -> Any:
        return TailorResult(
            status="approved",
            data={"title": "Senior Engineer", "summary": "Built things"},
            text="Resume body",
            attempts=1,
            errors=[],
            judge_verdict="ok",
            judge_issues=None,
        )

    monkeypatch.setattr(pipeline, "tailor_resume", _tailor)
    n = pipeline.run_tailor_stage(conn=db, router=_Router([]), profile=_profile())  # type: ignore[arg-type]
    assert n == 1
    row = db.execute(
        "SELECT tailored_resume_path, tailor_attempts FROM jobs WHERE url=?",
        ("https://a.com/1",),
    ).fetchone()
    assert row["tailored_resume_path"]
    assert row["tailor_attempts"] == 1


def test_run_tailor_stage_failed_bumps_attempts(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, full_description, fit_score) VALUES (?, ?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "greenhouse", "Backend role.", 9),
    )

    from nexscout.scoring.tailor import TailorResult

    def _tailor(**_kw: Any) -> Any:
        return TailorResult(
            status="failed_validation",
            data=None,
            text="",
            attempts=2,
            errors=["bad"],
        )

    monkeypatch.setattr(pipeline, "tailor_resume", _tailor)
    n = pipeline.run_tailor_stage(conn=db, router=_Router([]), profile=_profile())  # type: ignore[arg-type]
    assert n == 0
    row = db.execute("SELECT tailor_attempts FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["tailor_attempts"] == 2


def test_run_cover_stage_approved(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, full_description, tailored_resume_path, cover_required) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "gh", "desc", "/tmp/r.txt", 1),
    )

    from nexscout.scoring.cover_letter import CoverLetterResult

    def _write(**_kw: Any) -> Any:
        return CoverLetterResult(status="approved", text="Letter body", attempts=1)

    monkeypatch.setattr(pipeline, "write_cover_letter", _write)
    n = pipeline.run_cover_stage(conn=db, router=_Router([]), profile=_profile())  # type: ignore[arg-type]
    assert n == 1
    row = db.execute("SELECT cover_letter_path FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()
    assert row["cover_letter_path"]


def test_run_cover_stage_failed_bumps_attempts(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, full_description, tailored_resume_path, cover_required) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "gh", "desc", "/tmp/r.txt", 1),
    )

    from nexscout.scoring.cover_letter import CoverLetterResult

    def _write(**_kw: Any) -> Any:
        return CoverLetterResult(status="failed", text="", attempts=2)

    monkeypatch.setattr(pipeline, "write_cover_letter", _write)
    n = pipeline.run_cover_stage(conn=db, router=_Router([]), profile=_profile())  # type: ignore[arg-type]
    assert n == 0


# ---------------------------------------------------------------------------
# Render stage
# ---------------------------------------------------------------------------


def test_run_render_stage_uses_resume_json(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.execute(
        "INSERT INTO jobs (url, title, site, tailored_resume_path) VALUES (?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "gh", "/tmp/resume.txt"),
    )
    # The bundle_dir_for helper resolves under NEXSCOUT_DIR/bundles, so seed
    # a resume.json there.
    from nexscout.core.bundle import bundle_dir_for

    rowid = db.execute("SELECT rowid FROM jobs WHERE url=?", ("https://a.com/1",)).fetchone()["rowid"]
    bundle = bundle_dir_for(int(rowid))
    (bundle / "resume.json").write_text(json.dumps({"title": "Engineer", "summary": "Hi"}))

    calls: list[dict[str, Any]] = []

    def _render(**kw: Any) -> Path:
        calls.append(kw)
        return bundle / "resume.pdf"

    monkeypatch.setattr(pipeline, "render_resume_pdf", _render)
    n = pipeline.run_render_stage(conn=db, profile=_profile())
    assert n == 1
    assert calls
    assert calls[0]["data"]["title"] == "Engineer"


def test_run_render_stage_falls_back_to_txt(
    db: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    txt = tmp_path / "resume.txt"
    txt.write_text("Jane Q. Public\nStaff Engineer\n\nSUMMARY\nHi there.\n")
    db.execute(
        "INSERT INTO jobs (url, title, site, tailored_resume_path) VALUES (?, ?, ?, ?)",
        ("https://a.com/1", "Engineer", "gh", str(txt)),
    )
    captured: list[dict[str, Any]] = []

    def _render(**kw: Any) -> Any:
        captured.append(kw)
        return tmp_path / "resume.pdf"

    monkeypatch.setattr(pipeline, "render_resume_pdf", _render)
    n = pipeline.run_render_stage(conn=db, profile=_profile())
    assert n == 1
    # Title was recovered from the txt parser.
    assert captured[0]["data"]["title"] == "Staff Engineer"


def test_load_resume_data_corrupt_json_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "resume.json").write_text("not json {")
    txt = tmp_path / "resume.txt"
    txt.write_text("Name\nTitle\n")
    data = pipeline._load_resume_data(tmp_path, {"tailored_resume_path": str(txt), "title": "fallback"})
    assert data["title"] == "Title"


def test_load_resume_data_stub_when_nothing(tmp_path: Path) -> None:
    data = pipeline._load_resume_data(tmp_path, {"tailored_resume_path": "/nonexistent/path", "title": "Stub"})
    assert data["title"] == "Stub"
    assert data["skills"] == {}


# ---------------------------------------------------------------------------
# Public ``run()`` entry point
# ---------------------------------------------------------------------------


def test_run_dispatches_stages(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _record(name: str) -> Any:
        def _fn(**_kw: Any) -> int:
            calls.append(name)
            return 1

        return _fn

    monkeypatch.setattr(pipeline, "run_discover_stage", _record("discover"))
    monkeypatch.setattr(pipeline, "run_enrich_stage", _record("enrich"))
    monkeypatch.setattr(pipeline, "run_score_stage", _record("score"))
    monkeypatch.setattr(pipeline, "run_tailor_stage", _record("tailor"))
    monkeypatch.setattr(pipeline, "run_cover_stage", _record("cover"))
    monkeypatch.setattr(pipeline, "run_render_stage", _record("render"))

    counts = pipeline.run(["all"], profile=_profile(), conn=db, router=object())  # type: ignore[arg-type]
    assert calls == list(pipeline.STAGE_NAMES)
    assert all(v == 1 for v in counts.values())


def test_run_empty_stages_runs_all(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    for name in pipeline.STAGE_NAMES:

        def _fn(name: str = name) -> Any:
            def inner(**_kw: Any) -> int:
                calls.append(name)
                return 0

            return inner

        monkeypatch.setattr(pipeline, f"run_{name}_stage", _fn())

    pipeline.run([], profile=_profile(), conn=db, router=object())  # type: ignore[arg-type]
    assert set(calls) == set(pipeline.STAGE_NAMES)


def test_run_subset(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    for name in pipeline.STAGE_NAMES:

        def _fn(name: str = name) -> Any:
            def inner(**_kw: Any) -> int:
                calls.append(name)
                return 0

            return inner

        monkeypatch.setattr(pipeline, f"run_{name}_stage", _fn())

    pipeline.run(["score", "tailor"], profile=_profile(), conn=db, router=object())  # type: ignore[arg-type]
    assert calls == ["score", "tailor"]


# ---------------------------------------------------------------------------
# Streaming entry point — verify thread fan-out completes without hanging
# ---------------------------------------------------------------------------


def test_run_streaming_completes(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each stage runs in its own thread and terminates on upstream_done."""

    def _quick(name: str) -> Any:
        def _fn(**_kw: Any) -> int:
            return 0

        return _fn

    for name in pipeline.STAGE_NAMES:
        monkeypatch.setattr(pipeline, f"run_{name}_stage", _quick(name))

    counts = pipeline.run(
        ["all"],
        profile=_profile(),
        conn=db,
        router=object(),  # type: ignore[arg-type]
        stream=True,
        poll_interval=0.01,
    )
    assert set(counts) >= set(pipeline.STAGE_NAMES)


def test_streaming_stage_loop_drains_pending(db: sqlite3.Connection) -> None:
    """Direct unit test on the generic streaming worker."""
    db.execute("INSERT INTO jobs (url, title, site, full_description) VALUES ('https://a.com/1', 'x', 'gh', 'desc')")
    counts: dict[str, int] = {}
    upstream = threading.Event()
    upstream.set()
    stop = threading.Event()
    done = threading.Event()

    work_calls = [0]

    def do_batch() -> int:
        work_calls[0] += 1
        # First call drains everything.
        if work_calls[0] == 1:
            db.execute("UPDATE jobs SET fit_score=8 WHERE url='https://a.com/1'")
            return 1
        return 0

    pipeline._streaming_stage_loop(
        name="score",
        pending_sql="SELECT COUNT(*) FROM jobs WHERE fit_score IS NULL",
        pending_params=(),
        do_batch=do_batch,
        upstream_done=upstream,
        stop=stop,
        done=done,
        counts=counts,
        conn=db,
        poll_interval=0.01,
    )
    assert counts["score"] == 1
    assert done.is_set()


def test_streaming_stage_loop_exits_on_crash(db: sqlite3.Connection) -> None:
    counts: dict[str, int] = {}
    upstream = threading.Event()
    upstream.set()
    stop = threading.Event()
    done = threading.Event()

    def boom() -> int:
        raise RuntimeError("kaboom")

    pipeline._streaming_stage_loop(
        name="bad",
        pending_sql="SELECT 1",
        pending_params=(),
        do_batch=boom,
        upstream_done=upstream,
        stop=stop,
        done=done,
        counts=counts,
        conn=db,
        poll_interval=0.01,
    )
    assert done.is_set()


def test_pending_count_handles_none(db: sqlite3.Connection) -> None:
    n = pipeline._pending_count(db, "SELECT NULL")
    assert n == 0
