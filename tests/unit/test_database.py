"""Tests for ``core.database``."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nexscout.core.database import (
    _ALL_COLUMNS,
    ensure_columns,
    get_stats,
    init_db,
    insert_jobs,
    is_permanent_failure,
)


def test_init_db_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "j.sqlite"
    conn1 = init_db(db)
    cols1 = {row[1] for row in conn1.execute("PRAGMA table_info(jobs)").fetchall()}
    assert set(_ALL_COLUMNS.keys()) == cols1
    conn2 = init_db(db)
    cols2 = {row[1] for row in conn2.execute("PRAGMA table_info(jobs)").fetchall()}
    assert cols1 == cols2


def test_ensure_columns_adds_missing(tmp_path: Path) -> None:
    db = tmp_path / "j.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE jobs (url TEXT PRIMARY KEY, title TEXT)")
    conn.commit()

    # Initialise via our schema layer.
    init_db(db)
    added = ensure_columns(init_db(db))
    # Second call should add no further columns.
    assert added == []
    cols = {row[1] for row in init_db(db).execute("PRAGMA table_info(jobs)").fetchall()}
    assert "fit_score" in cols
    assert "apply_status" in cols


def test_insert_and_stats(tmp_path: Path) -> None:
    db = tmp_path / "j.sqlite"
    conn = init_db(db)
    rows = [
        {
            "url": f"https://example.com/{i}",
            "title": "Engineer",
            "site": "test",
            "strategy": "jobspy",
            "discovered_at": "2026-05-21T00:00:00+00:00",
            "fit_score": (i % 5) + 1,
            "full_description": "desc",
        }
        for i in range(5)
    ]
    new, dup = insert_jobs(rows, conn=conn)
    assert new == 5
    assert dup == 0
    new2, dup2 = insert_jobs(rows, conn=conn)
    assert new2 == 0
    assert dup2 == 5

    stats = get_stats(conn=conn)
    assert stats["total"] == 5
    assert stats["scored"] == 5
    assert "test" in stats["by_site"]


def test_permanent_failure_classification() -> None:
    assert is_permanent_failure("expired") is True
    assert is_permanent_failure("site_blocked:foo") is True
    assert is_permanent_failure("cloudflare_anything") is True
    assert is_permanent_failure("timeout") is False
    assert is_permanent_failure(None) is False
    assert is_permanent_failure("") is False
