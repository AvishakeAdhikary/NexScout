"""FastAPI TestClient coverage for every web route."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexscout.core.database import init_db
from nexscout.core.profile import Profile
from nexscout.web.app import create_app


def _seed_profile() -> None:
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "captcha": {"provider": "capsolver", "api_key": ""},
        }
    )
    profile.save()


@pytest.fixture
def db() -> Iterator[sqlite3.Connection]:
    conn = init_db()
    # Insert representative rows so the routes have something to render.
    conn.execute(
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status, discovered_at, applied_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/1", "Engineer A", "greenhouse", "Remote", 8, "applied", "2025", "2025"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status, discovered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("https://x.com/2", "Engineer B", "lever", "SF", 9, None, "2025"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status) VALUES (?, ?, ?, ?, ?, ?)",
        ("https://x.com/3", "Designer", "ashby", "NYC", 6, "failed"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status) VALUES (?, ?, ?, ?, ?, ?)",
        ("https://x.com/4", "Paused", "greenhouse", "Remote", 7, "paused_for_question"),
    )
    conn.execute(
        "INSERT INTO events (ts, kind, payload_json) VALUES (?, ?, ?)",
        ("2025-01-01T00:00:00Z", "discover", "{}"),
    )
    yield conn
    conn.close()


@pytest.fixture
def client(db: sqlite3.Connection) -> TestClient:
    _ = db
    _seed_profile()
    app = create_app()
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------


def test_dashboard_get(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Engineer" in resp.text or "stats" in resp.text or "NexScout" in resp.text


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_write_last_tick(tmp_path: Path) -> None:
    from nexscout.web.routes.dashboard import write_last_tick

    p = write_last_tick(channel="cli", root=tmp_path)
    assert p.exists()


def test_dashboard_openclaw_corrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when last-tick.json is corrupt the home route still renders."""
    from nexscout.web.routes import dashboard

    monkeypatch.setattr(dashboard, "nexscout_dir", lambda: tmp_path)
    monkeypatch.setattr(dashboard, "_profile_channel", lambda: None)
    (tmp_path / "last-tick.json").write_text("{not json")
    out = dashboard._openclaw_status()
    assert out["last_tick"] is None
    assert out["channel"] is None


def test_dashboard_openclaw_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.web.routes import dashboard

    monkeypatch.setattr(dashboard, "nexscout_dir", lambda: tmp_path / "no")
    monkeypatch.setattr(dashboard, "_profile_channel", lambda: None)
    out = dashboard._openclaw_status()
    assert out["last_tick"] is None
    assert out["channel"] is None


def test_dashboard_openclaw_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.web.routes import dashboard

    monkeypatch.setattr(dashboard, "nexscout_dir", lambda: tmp_path)
    (tmp_path / "last-tick.json").write_text('{"ts": "2025", "channel": "cli"}')
    out = dashboard._openclaw_status()
    assert out["last_tick"] == "2025"


def test_dashboard_renders_all_counters(client: TestClient) -> None:
    """The dashboard now surfaces every counter from ``get_stats``."""
    resp = client.get("/")
    assert resp.status_code == 200
    for label in (
        "Pending detail",
        "With description",
        "Detail errors",
        "Tailored",
        "Untailored eligible",
        "Tailor exhausted",
        "With cover letter",
        "Cover exhausted",
        "Apply errors",
        "Ready to apply",
        "Score distribution",
        "OpenClaw status",
        "Recent Events",
        "Pending Telegram deliveries",
    ):
        assert label in resp.text


def test_dashboard_empty_distribution_does_not_crash(client: TestClient, db: sqlite3.Connection) -> None:
    """Even with no scored jobs, the dashboard still renders (with a 'no scored jobs yet' card)."""
    db.execute("UPDATE jobs SET fit_score=NULL")
    resp = client.get("/")
    assert resp.status_code == 200
    assert "no scored jobs yet" in resp.text


def test_dashboard_pending_telegram_count(client: TestClient, db: sqlite3.Connection) -> None:
    """Pending Telegram deliveries counts pending_questions without channel_delivered_at."""
    db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/p1", "Sponsor?", "2025-01-01"),
    )
    db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at, channel_delivered_at) VALUES (?, ?, ?, ?)",
        ("https://x.com/p2", "Authorized?", "2025-01-01", "2025-01-01"),
    )
    resp = client.get("/")
    assert resp.status_code == 200
    # One row has channel_delivered_at NULL → indicator should read "1".
    assert 'id="pending-telegram-count">1</strong>' in resp.text


# ---------------------------------------------------------------------------
# Jobs routes
# ---------------------------------------------------------------------------


def test_jobs_list_default(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert "Engineer A" in resp.text or "Engineer" in resp.text


def test_jobs_list_filter_min_score(client: TestClient) -> None:
    resp = client.get("/jobs?min_score=9")
    assert resp.status_code == 200


def test_jobs_list_filter_status_applied(client: TestClient) -> None:
    resp = client.get("/jobs?status=applied")
    assert resp.status_code == 200


def test_jobs_list_filter_status_failed(client: TestClient) -> None:
    resp = client.get("/jobs?status=failed")
    assert resp.status_code == 200


def test_jobs_list_filter_status_pending(client: TestClient) -> None:
    resp = client.get("/jobs?status=pending")
    assert resp.status_code == 200


def test_jobs_list_filter_status_paused(client: TestClient) -> None:
    resp = client.get("/jobs?status=paused")
    assert resp.status_code == 200


def test_jobs_list_filter_by_site(client: TestClient) -> None:
    resp = client.get("/jobs?site=greenhouse")
    assert resp.status_code == 200


def test_jobs_list_sort_score(client: TestClient) -> None:
    resp = client.get("/jobs?sort=score")
    assert resp.status_code == 200


def test_jobs_list_sort_discovered(client: TestClient) -> None:
    resp = client.get("/jobs?sort=discovered")
    assert resp.status_code == 200


def test_job_detail_found(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    resp = client.get(f"/jobs/{row['rowid']}")
    assert resp.status_code == 200


def test_job_detail_not_found(client: TestClient) -> None:
    resp = client.get("/jobs/999999")
    assert resp.status_code == 404


def test_job_detail_includes_transcript(client: TestClient, db: sqlite3.Connection, tmp_path: Path) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    from nexscout.core.bundle import bundle_dir_for

    bundle = bundle_dir_for(int(row["rowid"]))
    (bundle / "transcript.jsonl").write_text('{"step":1}\nbad json\n{"step":2}\n')
    (bundle / "screenshots").mkdir(exist_ok=True)
    (bundle / "screenshots" / "001_first.png").write_bytes(b"png")
    resp = client.get(f"/jobs/{row['rowid']}")
    assert resp.status_code == 200


def test_bundle_file_route(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    jid = int(row["rowid"])
    from nexscout.core.bundle import bundle_dir_for

    bundle = bundle_dir_for(jid)
    (bundle / "resume.txt").write_text("hi")
    resp = client.get(f"/bundles/{jid}/resume.txt")
    assert resp.status_code == 200
    assert resp.text == "hi"


def test_bundle_file_in_screenshots(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    jid = int(row["rowid"])
    from nexscout.core.bundle import bundle_dir_for

    bundle = bundle_dir_for(jid)
    (bundle / "screenshots").mkdir(exist_ok=True)
    (bundle / "screenshots" / "shot.png").write_bytes(b"png")
    resp = client.get(f"/bundles/{jid}/shot.png")
    assert resp.status_code == 200


def test_bundle_file_missing(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    resp = client.get(f"/bundles/{int(row['rowid'])}/nothing.txt")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Applications routes
# ---------------------------------------------------------------------------


def test_applications_list(client: TestClient) -> None:
    resp = client.get("/applications")
    assert resp.status_code == 200


def test_applications_download_zip(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/1'").fetchone()
    jid = int(row["rowid"])
    from nexscout.core.bundle import bundle_dir_for

    bundle = bundle_dir_for(jid)
    (bundle / "resume.txt").write_text("hi")
    resp = client.get("/applications/download.zip")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"


# ---------------------------------------------------------------------------
# Profile routes
# ---------------------------------------------------------------------------


def test_profile_get(client: TestClient) -> None:
    resp = client.get("/profile")
    assert resp.status_code == 200


def test_profile_get_missing_profile(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When profile.yaml is gone the page still renders with an error message."""
    from nexscout.core import profile as profile_mod

    def _bad_from_path(path: Any = None) -> Any:
        raise profile_mod.ConfigError("missing")

    monkeypatch.setattr(profile_mod.Profile, "from_path", classmethod(lambda cls, path=None: _bad_from_path()))
    resp = client.get("/profile")
    assert resp.status_code == 200


def test_profile_post_valid(client: TestClient) -> None:
    yaml_text = (
        "me:\n  legal: x\n  pref: x\n  email: e@x.com\n  phone: \"1\"\ncaptcha:\n  provider: capsolver\n  api_key: ''\n"
    )
    resp = client.post("/profile", data={"yaml_text": yaml_text}, follow_redirects=False)
    # Redirects on success.
    assert resp.status_code == 303


def test_profile_post_invalid_yaml_raises(client: TestClient) -> None:
    """Bad YAML payload raises ValidationError through the handler — TestClient
    surfaces it as a 500. Either outcome is acceptable; we just confirm the
    POST round-trips through the handler at all."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        client.post("/profile", data={"yaml_text": "not a mapping"}, follow_redirects=False)


# ---------------------------------------------------------------------------
# Controls routes
# ---------------------------------------------------------------------------


def test_controls_pause_then_resume(client: TestClient) -> None:
    resp = client.post("/controls/pause")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"
    resp2 = client.post("/controls/resume")
    assert resp2.status_code == 200


def test_controls_tick(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.openclaw.tick.run", lambda **kw: {"applied": 0})
    resp = client.post("/controls/tick")
    # The tick now runs in a background thread and returns immediately (202).
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_controls_run_alias(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """`/controls/run` is the friendly alias the dashboard button posts to."""
    monkeypatch.setattr("nexscout.openclaw.tick.run", lambda **kw: {"applied": 0})
    resp = client.post("/controls/run")
    assert resp.status_code == 202


def test_controls_status(client: TestClient) -> None:
    """`/controls/status` returns the background-run snapshot for polling."""
    resp = client.get("/controls/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body
    assert "message" in body
    assert "paused" in body


def test_controls_status_html_partial(client: TestClient) -> None:
    """The HTMX-polled status partial renders a `#run-status` fragment."""
    resp = client.get("/controls/status/html")
    assert resp.status_code == 200
    assert 'id="run-status"' in resp.text
    # It's a fragment, not a full page.
    assert "<header" not in resp.text


# ---------------------------------------------------------------------------
# API + metrics routes
# ---------------------------------------------------------------------------


def test_api_stats(client: TestClient) -> None:
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    assert "total" in resp.json()


def test_api_jobs(client: TestClient) -> None:
    resp = client.get("/api/jobs?min_score=0&limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_metrics(client: TestClient) -> None:
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    assert "nexscout_jobs_total" in resp.text


def test_top_level_metrics(client: TestClient) -> None:
    """The Prometheus-conventional top-level `/metrics` is also mounted."""
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "nexscout_jobs_total" in resp.text


def test_api_charts(client: TestClient) -> None:
    """`/api/charts` feeds the dashboard graphs (score distribution + pipeline)."""
    resp = client.get("/api/charts")
    assert resp.status_code == 200
    data = resp.json()
    assert "score_distribution" in data
    assert "labels" in data["score_distribution"]
    assert "counts" in data["score_distribution"]
    assert "pipeline" in data
    assert data["pipeline"]["labels"] == ["Discovered", "Scored", "Tailored", "Applied"]
    assert "has_data" in data


def test_api_applications(client: TestClient) -> None:
    """`/api/applications` returns the applied jobs as JSON."""
    resp = client.get("/api/applications")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    # Seed data has one applied row → "Engineer A" / greenhouse.
    assert any(r.get("title") == "Engineer A" for r in rows)
    # Every row must carry the standard application fields.
    for r in rows:
        assert "url" in r
        assert "site" in r
        assert "applied_at" in r


def test_api_questions(client: TestClient, db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/q1", "Sponsor?", "2025-01-01"),
    )
    resp = client.get("/api/questions")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(r["question"] == "Sponsor?" for r in rows)
    # channel_delivered_at is exposed in the JSON payload.
    assert all("channel_delivered_at" in r for r in rows)


def test_api_answer_json_success(client: TestClient, db: sqlite3.Connection) -> None:
    cur = db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?) RETURNING id",
        ("https://x.com/q2", "Authorized?", "2025-01-01"),
    )
    qid = int(cur.fetchone()["id"])
    resp = client.post("/api/answer/json", json={"question_id": qid, "reply": "Yes"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    row = db.execute("SELECT answer FROM pending_questions WHERE id=?", (qid,)).fetchone()
    assert row["answer"] == "Yes"


def test_api_answer_json_not_found(client: TestClient) -> None:
    resp = client.post("/api/answer/json", json={"question_id": 999999, "reply": "x"})
    assert resp.status_code == 404


def test_api_reapply_success(client: TestClient, db: sqlite3.Connection) -> None:
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/3'").fetchone()
    jid = int(row["rowid"])
    # The seed row is 'failed' — reapply clears that.
    resp = client.post("/api/reapply", json={"job_id": jid})
    assert resp.status_code == 200
    after = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE rowid=?", (jid,)).fetchone()
    assert after["apply_status"] is None
    assert int(after["apply_attempts"]) == 0


def test_api_reapply_not_found(client: TestClient) -> None:
    resp = client.post("/api/reapply", json={"job_id": 999999})
    assert resp.status_code == 404


def test_reapply_form_submits(client: TestClient, db: sqlite3.Connection) -> None:
    """The form-style POST used by job_detail.html resets apply state."""
    row = db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/3'").fetchone()
    jid = int(row["rowid"])
    resp = client.post("/api/reapply", data={"job_id": str(jid)}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jobs/{jid}"


def test_profile_migrate_route(client: TestClient) -> None:
    resp = client.get("/profile/migrate", follow_redirects=False)
    # Redirects whether the profile is current or not.
    assert resp.status_code == 303


def test_jobs_htmx_returns_fragment(client: TestClient) -> None:
    """HTMX requests get just the `#jobs-table` fragment, not the full page."""
    resp = client.get("/jobs", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert '<table id="jobs-table"' in resp.text
    # The fragment should not include the sidebar or filter form.
    assert "<aside" not in resp.text
    assert 'id="jobs-filter"' not in resp.text


def test_api_jobs_site_filter(client: TestClient) -> None:
    resp = client.get("/api/jobs?site=greenhouse&min_score=0&limit=10")
    assert resp.status_code == 200
    rows = resp.json()
    for r in rows:
        assert r["site"] == "greenhouse"


def test_api_stats_shape(client: TestClient) -> None:
    """`/api/stats` exposes every counter documented in §5."""
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "total",
        "by_site",
        "pending_detail",
        "with_description",
        "detail_errors",
        "scored",
        "unscored",
        "score_distribution",
        "tailored",
        "untailored_eligible",
        "tailor_exhausted",
        "with_cover_letter",
        "cover_exhausted",
        "applied",
        "apply_errors",
        "ready_to_apply",
    ):
        assert key in data


# ---------------------------------------------------------------------------
# App factory wiring
# ---------------------------------------------------------------------------


def test_create_app_404_handler() -> None:
    _seed_profile()
    app = create_app()
    c = TestClient(app)
    resp = c.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    assert "404" in resp.text


# ---------------------------------------------------------------------------
# Score-a-single-job endpoint + pagination
# ---------------------------------------------------------------------------


def test_score_job_now_htmx_updates_row(
    client: TestClient, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The "Score now" button (HTMX) re-scores one job and returns the new row."""
    from nexscout.scoring import scorer

    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: (8, "python, ml\nStrong match."))
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/3'").fetchone()["rowid"])
    # Make it eligible for the score stage: enriched (has a description) but unscored.
    db.execute(
        "UPDATE jobs SET fit_score=NULL, full_description='desc', detail_scraped_at='2025' WHERE rowid=?", (jid,)
    )
    resp = client.post(f"/jobs/{jid}/score", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<tr" in resp.text
    assert "8/10" in resp.text
    after = db.execute("SELECT fit_score FROM jobs WHERE rowid=?", (jid,)).fetchone()
    assert int(after["fit_score"]) == 8


def test_score_job_now_form_redirects(
    client: TestClient, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain form POST (job detail page) redirects back to the job."""
    from nexscout.scoring import scorer

    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: (7, "x\ny"))
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/2'").fetchone()["rowid"])
    resp = client.post(f"/jobs/{jid}/score", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jobs/{jid}"


def test_score_job_now_not_found(client: TestClient) -> None:
    resp = client.post("/jobs/999999/score", headers={"HX-Request": "true"})
    assert resp.status_code == 404


def test_score_job_now_failure_keeps_existing_score(
    client: TestClient, db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed scoring (0) must not clobber a previously good score."""
    from nexscout.scoring import scorer

    monkeypatch.setattr(scorer, "score_job", lambda *a, **k: (0, "error: boom"))
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/3'").fetchone()["rowid"])
    db.execute(
        "UPDATE jobs SET fit_score=NULL, full_description='desc', detail_scraped_at='2025' WHERE rowid=?", (jid,)
    )
    resp = client.post(f"/jobs/{jid}/score", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    after = db.execute("SELECT fit_score FROM jobs WHERE rowid=?", (jid,)).fetchone()
    assert after["fit_score"] is None  # a 0/failed score must not be persisted


def test_jobs_list_shows_pagination(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert "Showing" in resp.text
    assert "of 4" in resp.text  # 4 seed jobs


def test_applications_shows_pagination(client: TestClient) -> None:
    resp = client.get("/applications")
    assert resp.status_code == 200
    assert "Showing" in resp.text


def test_questions_shows_pagination(client: TestClient, db: sqlite3.Connection) -> None:
    db.execute(
        "INSERT INTO pending_questions (job_url, question, asked_at) VALUES (?, ?, ?)",
        ("https://x.com/qp", "Visa?", "2025-01-01"),
    )
    resp = client.get("/questions")
    assert resp.status_code == 200
    assert "Showing" in resp.text


# ---------------------------------------------------------------------------
# Pipeline panel + control + stage-lock + logs
# ---------------------------------------------------------------------------


def test_pipeline_panel_renders(client: TestClient) -> None:
    resp = client.get("/controls/pipeline")
    assert resp.status_code == 200
    assert "Run one full pass now" in resp.text
    assert "Discover" in resp.text and "Apply" in resp.text


def test_pipeline_pause_resume_is_real(client: TestClient) -> None:
    from nexscout.core import pipeline_status as ps

    assert client.post("/controls/pipeline/pause").status_code == 200
    assert ps.is_paused() is True
    assert client.post("/controls/pipeline/resume").status_code == 200
    assert ps.is_paused() is False


def test_pipeline_stop_sets_flag(client: TestClient) -> None:
    from nexscout.core import pipeline_status as ps

    ps.clear_stop()
    assert client.post("/controls/pipeline/stop").status_code == 200
    assert ps.stop_requested() is True
    ps.clear_stop()


def test_pipeline_stage_toggle(client: TestClient) -> None:
    from nexscout.core import pipeline_status as ps

    assert ps.set_stage_enabled("apply", True) is not None  # start enabled
    client.post("/controls/pipeline/stage/apply/toggle")
    assert ps.stage_enabled("apply") is False
    client.post("/controls/pipeline/stage/apply/toggle")
    assert ps.stage_enabled("apply") is True


def test_stage_lock_blocks_ineligible(client: TestClient, db: sqlite3.Connection) -> None:
    """Requesting a stage a job isn't eligible for is a no-op (the stage-lock)."""
    # Job 2 has no description/tailored résumé → eligible for 'enrich', not 'apply'.
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/2'").fetchone()["rowid"])
    before = db.execute("SELECT apply_status FROM jobs WHERE rowid=?", (jid,)).fetchone()["apply_status"]
    resp = client.post(f"/jobs/{jid}/stage/apply", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    after = db.execute("SELECT apply_status FROM jobs WHERE rowid=?", (jid,)).fetchone()["apply_status"]
    assert after == before  # apply did not run


def test_per_job_apply_queues_when_eligible(client: TestClient, db: sqlite3.Connection) -> None:
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/3'").fetchone()["rowid"])
    # Make it apply-eligible: read + scored high + tailored + a prior failure.
    db.execute(
        "UPDATE jobs SET detail_scraped_at='2025', full_description='desc', fit_score=8, "
        "tailored_resume_path='/tmp/r.txt', apply_status='failed', apply_attempts=1 WHERE rowid=?",
        (jid,),
    )
    resp = client.post(f"/jobs/{jid}/stage/apply", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    row = db.execute("SELECT apply_status, apply_attempts FROM jobs WHERE rowid=?", (jid,)).fetchone()
    assert row["apply_status"] is None
    assert int(row["apply_attempts"]) == 0


def test_run_job_stage_unknown(client: TestClient, db: sqlite3.Connection) -> None:
    jid = int(db.execute("SELECT rowid FROM jobs WHERE url='https://x.com/2'").fetchone()["rowid"])
    resp = client.post(f"/jobs/{jid}/stage/bogus", headers={"HX-Request": "true"})
    assert resp.status_code == 422


def test_logs_page_renders(client: TestClient) -> None:
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert "Live logs" in resp.text


def test_logs_unknown_role_falls_back(client: TestClient) -> None:
    resp = client.get("/logs?role=bogus")
    assert resp.status_code == 200
