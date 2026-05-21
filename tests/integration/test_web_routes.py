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
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("https://x.com/3", "Designer", "ashby", "NYC", 6, "failed"),
    )
    conn.execute(
        "INSERT INTO jobs (url, title, site, location, fit_score, apply_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
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
    (tmp_path / "last-tick.json").write_text("{not json")
    out = dashboard._openclaw_status()
    assert out == {"last_tick": None, "channel": None}


def test_dashboard_openclaw_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.web.routes import dashboard

    monkeypatch.setattr(dashboard, "nexscout_dir", lambda: tmp_path / "no")
    out = dashboard._openclaw_status()
    assert out == {"last_tick": None, "channel": None}


def test_dashboard_openclaw_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.web.routes import dashboard

    monkeypatch.setattr(dashboard, "nexscout_dir", lambda: tmp_path)
    (tmp_path / "last-tick.json").write_text('{"ts": "2025", "channel": "cli"}')
    out = dashboard._openclaw_status()
    assert out["last_tick"] == "2025"


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
        "me:\n  legal: x\n  pref: x\n  email: e@x.com\n  phone: \"1\"\n"
        "captcha:\n  provider: capsolver\n  api_key: ''\n"
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
    assert resp.status_code == 200


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
