"""SQLite layer: schema registry, idempotent init, ensure_columns, stats.

Single source of truth for column definitions lives in :data:`_ALL_COLUMNS`.
``init_db`` creates the table if missing. ``ensure_columns`` reads the
existing schema and ALTERs missing columns in — forward-only migrations.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from .config import database_path, ensure_dirs

# ---------------------------------------------------------------------------
# Column registry — every column ever used by every stage (§5).
# ---------------------------------------------------------------------------

_ALL_COLUMNS: dict[str, str] = {
    # Discovery
    "url": "TEXT PRIMARY KEY",
    "title": "TEXT",
    "salary": "TEXT",
    "description": "TEXT",
    "location": "TEXT",
    "site": "TEXT",
    "strategy": "TEXT",
    "discovered_at": "TEXT",
    "web_search_query": "TEXT",
    # Enrichment
    "full_description": "TEXT",
    "application_url": "TEXT",
    "detail_scraped_at": "TEXT",
    "detail_error": "TEXT",
    # Scoring
    "fit_score": "INTEGER",
    "score_reasoning": "TEXT",
    "scored_at": "TEXT",
    # Tailoring
    "tailored_resume_path": "TEXT",
    "tailored_at": "TEXT",
    "tailor_attempts": "INTEGER DEFAULT 0",
    "latex_template": "TEXT",
    # Cover letter
    "cover_letter_path": "TEXT",
    "cover_letter_at": "TEXT",
    "cover_attempts": "INTEGER DEFAULT 0",
    "cover_required": "INTEGER DEFAULT 0",
    # Application
    "applied_at": "TEXT",
    "apply_status": "TEXT",
    "apply_error": "TEXT",
    "apply_attempts": "INTEGER DEFAULT 0",
    "agent_id": "TEXT",
    "last_attempted_at": "TEXT",
    "apply_duration_ms": "INTEGER",
    "apply_task_id": "TEXT",
    "verification_confidence": "TEXT",
    "apply_backend": "TEXT",
    "bundle_dir": "TEXT",
    "captcha_solved": "INTEGER DEFAULT 0",
    "cost_usd": "REAL DEFAULT 0",
    "profile_addendum_json": "TEXT",
}

# Permanent-failure reason set (§5)
PERMANENT_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "expired",
        "captcha",
        "login_issue",
        "not_eligible_location",
        "not_eligible_salary",
        "already_applied",
        "account_required",
        "not_a_job_application",
        "unsafe_permissions",
        "unsafe_verification",
        "sso_required",
        "site_blocked",
        "cloudflare_blocked",
        "blocked_by_cloudflare",
    }
)

_PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


def is_permanent_failure(reason: str | None) -> bool:
    """Classify whether an apply failure reason should never be retried."""
    if not reason:
        return False
    r = reason.strip().lower()
    if r in PERMANENT_FAILURE_REASONS:
        return True
    return any(r.startswith(p) for p in _PERMANENT_PREFIXES)


# ---------------------------------------------------------------------------
# Connection management (thread-local)
# ---------------------------------------------------------------------------

_local = threading.local()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=10.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn(path: Path | None = None) -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    p = path or database_path()
    cached = getattr(_local, "conn", None)
    cached_path = getattr(_local, "path", None)
    if cached is not None and cached_path == str(p):
        return cached  # type: ignore[no-any-return]
    if cached is not None:
        with suppress(sqlite3.Error):
            cached.close()
    _local.conn = _connect(p)
    _local.path = str(p)
    return _local.conn


@contextmanager
def transaction(conn: sqlite3.Connection | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager wrapping BEGIN IMMEDIATE / COMMIT / ROLLBACK."""
    c = conn or get_conn()
    c.execute("BEGIN IMMEDIATE")
    try:
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


# ---------------------------------------------------------------------------
# Schema lifecycle
# ---------------------------------------------------------------------------


def _build_create_sql() -> str:
    cols_sql = ",\n  ".join(f"{name} {ddl}" for name, ddl in _ALL_COLUMNS.items())
    return f"CREATE TABLE IF NOT EXISTS jobs (\n  {cols_sql}\n)"


def init_db(path: Path | None = None) -> sqlite3.Connection:
    """Idempotent: create ``jobs``, ``pending_questions``, ``events`` if missing."""
    ensure_dirs()
    conn = get_conn(path)
    conn.executescript(
        _build_create_sql()
        + """;
        CREATE TABLE IF NOT EXISTS pending_questions (
          id INTEGER PRIMARY KEY,
          job_url TEXT,
          question TEXT,
          asked_at TEXT,
          channel TEXT,
          answered_at TEXT,
          answer TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY,
          ts TEXT,
          kind TEXT,
          payload_json TEXT
        );
        """
    )
    ensure_columns(conn)
    # Indexes referenced columns may have just been added by ensure_columns.
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_apply_status ON jobs(apply_status);
        CREATE INDEX IF NOT EXISTS idx_jobs_fit_score ON jobs(fit_score);
        CREATE INDEX IF NOT EXISTS idx_jobs_site ON jobs(site);
        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
        """
    )
    return conn


def ensure_columns(conn: sqlite3.Connection | None = None) -> list[str]:
    """ALTER TABLE jobs to add any columns missing relative to ``_ALL_COLUMNS``.

    Returns the list of added column names.
    """
    c = conn or get_conn()
    existing: set[str] = {row[1] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}
    if not existing:
        # Table doesn't exist yet (caller forgot init_db) — create it.
        c.executescript(_build_create_sql())
        existing = {row[1] for row in c.execute("PRAGMA table_info(jobs)").fetchall()}

    added: list[str] = []
    for name, ddl in _ALL_COLUMNS.items():
        if name in existing:
            continue
        # SQLite ALTER TABLE ADD COLUMN cannot declare PRIMARY KEY, so strip it.
        safe_ddl = ddl.replace("PRIMARY KEY", "").strip()
        c.execute(f"ALTER TABLE jobs ADD COLUMN {name} {safe_ddl}")
        added.append(name)
    return added


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    val = row[0]
    return int(val) if val is not None else 0


def get_stats(conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Return the counters used by the CLI ``status`` command and web UI."""
    c = conn or get_conn()
    total = _scalar(c, "SELECT COUNT(*) FROM jobs")
    by_site: dict[str, int] = {
        row["site"] or "": int(row["n"])
        for row in c.execute("SELECT site, COUNT(*) AS n FROM jobs GROUP BY site").fetchall()
    }
    pending_detail = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL")
    with_description = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL")
    detail_errors = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE detail_error IS NOT NULL")
    scored = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE fit_score IS NOT NULL")
    unscored = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE fit_score IS NULL AND full_description IS NOT NULL",
    )
    distribution: dict[int, int] = {
        int(row["fit_score"]): int(row["n"])
        for row in c.execute(
            "SELECT fit_score, COUNT(*) AS n FROM jobs WHERE fit_score IS NOT NULL GROUP BY fit_score"
        ).fetchall()
    }
    tailored = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL")
    untailored_eligible = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NULL "
        "AND fit_score IS NOT NULL AND tailor_attempts < 5",
    )
    tailor_exhausted = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NULL AND tailor_attempts >= 5",
    )
    with_cover_letter = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NOT NULL")
    cover_exhausted = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE cover_letter_path IS NULL AND cover_attempts >= 3",
    )
    applied = _scalar(c, "SELECT COUNT(*) FROM jobs WHERE apply_status = 'applied'")
    apply_errors = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE apply_status IN ('failed','captcha','login_issue','expired')",
    )
    ready_to_apply = _scalar(
        c,
        "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
        "AND (apply_status IS NULL OR apply_status = 'failed')",
    )
    return {
        "total": total,
        "by_site": by_site,
        "pending_detail": pending_detail,
        "with_description": with_description,
        "detail_errors": detail_errors,
        "scored": scored,
        "unscored": unscored,
        "score_distribution": distribution,
        "tailored": tailored,
        "untailored_eligible": untailored_eligible,
        "tailor_exhausted": tailor_exhausted,
        "with_cover_letter": with_cover_letter,
        "cover_exhausted": cover_exhausted,
        "applied": applied,
        "apply_errors": apply_errors,
        "ready_to_apply": ready_to_apply,
    }


# ---------------------------------------------------------------------------
# Apply-stage helpers (atomic acquire — actual orchestrator wires in M7).
# ---------------------------------------------------------------------------


def acquire_job(
    *,
    agent_id: str,
    max_attempts: int,
    min_score: int,
    blocked_sites: list[str] | None = None,
    blocked_patterns: list[str] | None = None,
    now_iso: str,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Row | None:
    """Atomically acquire the highest-scoring eligible job for this worker.

    Implementation per §5; returns the job row or None if nothing eligible.
    """
    c = conn or get_conn()
    blocked_sites = blocked_sites or []
    blocked_patterns = blocked_patterns or []

    site_clause = ""
    site_params: list[Any] = []
    if blocked_sites:
        placeholders = ",".join("?" for _ in blocked_sites)
        site_clause = f" AND (site IS NULL OR site NOT IN ({placeholders}))"
        site_params.extend(blocked_sites)

    url_clauses: list[str] = []
    url_params: list[Any] = []
    for pat in blocked_patterns:
        url_clauses.append("url NOT LIKE ?")
        url_params.append(pat)
    url_clause = (" AND " + " AND ".join(url_clauses)) if url_clauses else ""

    select_sql = (
        "SELECT url, title, site, application_url, tailored_resume_path, "
        "fit_score, location, full_description, cover_letter_path "
        "FROM jobs "
        "WHERE tailored_resume_path IS NOT NULL "
        "  AND (apply_status IS NULL OR apply_status = 'failed') "
        "  AND (apply_attempts IS NULL OR apply_attempts < ?) "
        "  AND fit_score >= ? "
        f"{site_clause}"
        f"{url_clause} "
        "ORDER BY fit_score DESC, url "
        "LIMIT 1"
    )

    with transaction(c):
        row = c.execute(select_sql, (max_attempts, min_score, *site_params, *url_params)).fetchone()
        if row is None:
            return None
        c.execute(
            "UPDATE jobs SET apply_status='in_progress', agent_id=?, last_attempted_at=? WHERE url=?",
            (agent_id, now_iso, row["url"]),
        )
        return row


def mark_apply_result(
    *,
    url: str,
    status: str,
    error: str | None,
    duration_ms: int | None,
    now_iso: str,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Record an apply outcome, bumping attempts and freezing on permanent failure."""
    c = conn or get_conn()
    attempts_bump = 99 if status == "failed" and is_permanent_failure(error) else 1
    c.execute(
        "UPDATE jobs SET apply_status=?, apply_error=?, applied_at=CASE WHEN ?='applied' THEN ? ELSE applied_at END, "
        "apply_duration_ms=?, apply_attempts=COALESCE(apply_attempts,0)+? "
        "WHERE url=?",
        (status, error, status, now_iso, duration_ms, attempts_bump, url),
    )


# ---------------------------------------------------------------------------
# Insert helpers (used by discovery)
# ---------------------------------------------------------------------------


def insert_jobs(rows: list[dict[str, Any]], conn: sqlite3.Connection | None = None) -> tuple[int, int]:
    """Bulk-insert jobs with ``ON CONFLICT(url) DO NOTHING``.

    Returns (new_count, duplicate_count).
    """
    if not rows:
        return 0, 0
    c = conn or get_conn()
    new_count = 0
    dup_count = 0
    for row in rows:
        cols = list(row.keys())
        placeholders = ",".join("?" for _ in cols)
        col_list = ",".join(cols)
        sql = f"INSERT INTO jobs ({col_list}) VALUES ({placeholders}) ON CONFLICT(url) DO NOTHING"
        cur = c.execute(sql, tuple(row[k] for k in cols))
        if cur.rowcount > 0:
            new_count += 1
        else:
            dup_count += 1
    return new_count, dup_count


def log_event(kind: str, payload_json: str, ts_iso: str, conn: sqlite3.Connection | None = None) -> None:
    """Append a row to ``events``."""
    c = conn or get_conn()
    c.execute(
        "INSERT INTO events (ts, kind, payload_json) VALUES (?, ?, ?)",
        (ts_iso, kind, payload_json),
    )
