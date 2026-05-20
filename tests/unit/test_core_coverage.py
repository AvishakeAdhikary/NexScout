"""Coverage tests for `core/{config,logging,settings,bundle,database}`.

These exercise the previously-untested branches so the §23 ≥90 % target on
``core/`` is met without weakening any existing tests.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from nexscout.core import bundle as bundle_mod
from nexscout.core import config as config_mod
from nexscout.core import logging as logging_mod
from nexscout.core import settings as settings_mod
from nexscout.core.database import (
    ensure_columns,
    get_conn,
    init_db,
    insert_jobs,
    is_permanent_failure,
    log_event,
    mark_apply_result,
)

# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------


class TestConfig:
    def test_nexscout_dir_honours_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / "stash"))
        assert config_mod.nexscout_dir() == (tmp_path / "stash").resolve()

    def test_nexscout_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NEXSCOUT_DIR", raising=False)
        assert config_mod.nexscout_dir() == Path.home() / ".nexscout"

    def test_path_helpers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path))
        assert config_mod.profile_path().name == "profile.yaml"
        assert config_mod.database_path().name == "nexscout.sqlite"
        assert config_mod.budget_db_path().name == "budget.sqlite"
        assert config_mod.employers_path().name == "employers.yaml"
        assert config_mod.sites_path().name == "sites.yaml"
        assert config_mod.applications_dir().name == "applications"
        assert config_mod.chrome_workers_dir().name == "chrome-workers"
        assert config_mod.apply_workers_dir().name == "apply-workers"

    def test_ensure_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / "fresh"))
        config_mod.ensure_dirs()
        for sub in ("applications", "chrome-workers", "apply-workers"):
            assert (tmp_path / "fresh" / sub).is_dir()

    def test_get_chrome_path_honours_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = tmp_path / "chrome.exe"
        fake.write_bytes(b"")
        monkeypatch.setenv("CHROME_PATH", str(fake))
        assert config_mod.get_chrome_path() == str(fake)

    def test_get_chrome_path_missing_returns_something_or_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CHROME_PATH", raising=False)
        # On CI runners with no Chrome / Chromium installed, this returns None.
        # On dev boxes, it returns a path. We accept both.
        result = config_mod.get_chrome_path()
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# logging.py
# ---------------------------------------------------------------------------


class TestLogging:
    def test_setup_rich_mode(self) -> None:
        logging_mod.setup_logging("DEBUG", json_mode=False)
        root = logging.getLogger()
        assert root.level == logging.DEBUG
        assert root.handlers, "rich handler must be installed"
        root.handlers.clear()

    def test_setup_json_mode(self) -> None:
        logging_mod.setup_logging("INFO", json_mode=True)
        root = logging.getLogger()
        assert root.level == logging.INFO
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
        root.handlers.clear()

    def test_get_logger_returns_named_logger(self) -> None:
        log = logging_mod.get_logger("nexscout.test")
        assert log.name == "nexscout.test"

    def test_json_formatter_emits_valid_json(self) -> None:
        import json

        rec = logging.LogRecord(
            name="x",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        rec.custom_field = "extra"  # type: ignore[attr-defined]
        out = logging_mod.JsonFormatter().format(rec)
        payload = json.loads(out)
        assert payload["msg"] == "hello world"
        assert payload["level"] == "INFO"
        assert payload["custom_field"] == "extra"


# ---------------------------------------------------------------------------
# settings.py
# ---------------------------------------------------------------------------


class TestSettings:
    def test_get_settings_reads_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Reset the lazy singleton.
        monkeypatch.setattr(settings_mod, "_settings", None)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("CAPTCHA_API_KEY", "cap-test")
        s = settings_mod.get_settings()
        assert s.openai_api_key == "sk-test"
        assert s.captcha_api_key == "cap-test"

    def test_get_settings_caches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings_mod, "_settings", None)
        first = settings_mod.get_settings()
        second = settings_mod.get_settings()
        assert first is second


# ---------------------------------------------------------------------------
# bundle.py
# ---------------------------------------------------------------------------


class TestBundle:
    def test_bundle_dir_for_creates_dir(self, tmp_path: Path) -> None:
        bdir = bundle_mod.bundle_dir_for(42, root=tmp_path)
        assert bdir.is_dir()
        assert bdir.name == "000042"
        assert (bdir / "screenshots").is_dir()

    def test_write_bundle_file_str_and_bytes(self, tmp_path: Path) -> None:
        p1 = bundle_mod.write_bundle_file(1, "note.txt", "hello", root=tmp_path)
        assert p1.read_text(encoding="utf-8") == "hello"
        p2 = bundle_mod.write_bundle_file(1, "img.bin", b"\x00\x01\x02", root=tmp_path)
        assert p2.read_bytes() == b"\x00\x01\x02"

    def test_read_bundle_file(self, tmp_path: Path) -> None:
        bundle_mod.write_bundle_file(7, "n.txt", "x", root=tmp_path)
        assert bundle_mod.read_bundle_file(7, "n.txt", root=tmp_path) == "x"

    def test_bundle_dir_uses_applications_dir_when_root_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXSCOUT_DIR", str(tmp_path / "ns"))
        bdir = bundle_mod.bundle_dir_for(99)
        assert bdir.parent.name == "applications"


# ---------------------------------------------------------------------------
# database.py — fewer-covered helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    return init_db(tmp_path / "x.sqlite")


class TestDatabase:
    def test_insert_jobs_new_and_dupe(self, db: sqlite3.Connection) -> None:
        rows = [
            {"url": "https://a.com/1", "title": "X", "site": "s"},
            {"url": "https://a.com/1", "title": "Y", "site": "s"},  # dupe
            {"url": "https://a.com/2", "title": "Z", "site": "s"},
        ]
        new, dupes = insert_jobs(rows, db)
        assert new == 2
        assert dupes == 1

    def test_insert_jobs_empty(self, db: sqlite3.Connection) -> None:
        assert insert_jobs([], db) == (0, 0)

    def test_ensure_columns_idempotent(self, tmp_path: Path) -> None:
        conn = init_db(tmp_path / "y.sqlite")
        added = ensure_columns(conn)
        # init_db already added everything; second call should be a no-op.
        assert added == []

    def test_ensure_columns_on_empty_table(self, tmp_path: Path) -> None:
        # Create a DB without the jobs table; ensure_columns must create it.
        path = tmp_path / "blank.sqlite"
        conn = sqlite3.connect(str(path))
        ensure_columns(conn)
        # The table exists now and has every registry column.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
        assert "url" in cols
        assert "fit_score" in cols
        conn.close()

    def test_log_event(self, db: sqlite3.Connection) -> None:
        log_event("apply", '{"x":1}', "2026-05-21T00:00:00Z", db)
        row = db.execute("SELECT * FROM events").fetchone()
        assert row["kind"] == "apply"
        assert row["payload_json"] == '{"x":1}'

    def test_mark_apply_result_marks_permanent(self, db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT INTO jobs (url, fit_score, tailored_resume_path, apply_status, apply_attempts) "
            "VALUES (?, ?, ?, ?, ?)",
            ("https://x", 8, "/tmp", "in_progress", 1),
        )
        mark_apply_result(
            url="https://x",
            status="failed",
            error="sso_required",
            duration_ms=1234,
            now_iso="2026-05-21T00:00:00Z",
            conn=db,
        )
        row = db.execute(
            "SELECT apply_status, apply_error, apply_attempts FROM jobs WHERE url=?",
            ("https://x",),
        ).fetchone()
        assert row["apply_status"] == "failed"
        assert row["apply_attempts"] == 100  # 1 + 99 frozen

    def test_mark_apply_result_records_applied_at_only_on_applied(self, db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT INTO jobs (url, fit_score, tailored_resume_path) VALUES (?, ?, ?)",
            ("https://x", 8, "/tmp"),
        )
        mark_apply_result(
            url="https://x",
            status="applied",
            error=None,
            duration_ms=None,
            now_iso="2026-05-21T00:00:00Z",
            conn=db,
        )
        row = db.execute("SELECT applied_at FROM jobs WHERE url=?", ("https://x",)).fetchone()
        assert row["applied_at"] == "2026-05-21T00:00:00Z"

    def test_is_permanent_failure_classifier(self) -> None:
        assert is_permanent_failure("sso_required") is True
        assert is_permanent_failure("expired") is True
        assert is_permanent_failure("site_blocked_anywhere") is True
        assert is_permanent_failure("cloudflare_403") is True
        assert is_permanent_failure("page_error") is False
        assert is_permanent_failure(None) is False
        assert is_permanent_failure("") is False

    def test_get_conn_thread_local_cache(self, tmp_path: Path) -> None:
        p = tmp_path / "tl.sqlite"
        init_db(p)
        first = get_conn(p)
        second = get_conn(p)
        # Same path -> same cached connection
        assert first is second

    def test_get_conn_recreates_on_path_change(self, tmp_path: Path) -> None:
        a = tmp_path / "a.sqlite"
        b = tmp_path / "b.sqlite"
        init_db(a)
        init_db(b)
        ca = get_conn(a)
        cb = get_conn(b)
        assert ca is not cb
