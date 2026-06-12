"""Unit tests for the humandate Jinja filter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from nexscout.web.filters import humandate

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)


def test_humandate_empty() -> None:
    assert humandate(None) == ""
    assert humandate("") == ""


def test_humandate_just_now() -> None:
    assert humandate((NOW - timedelta(seconds=10)).isoformat(), now=NOW) == "just now"


def test_humandate_minutes() -> None:
    assert humandate((NOW - timedelta(minutes=5)).isoformat(), now=NOW) == "5 minutes ago"
    assert humandate((NOW - timedelta(minutes=1)).isoformat(), now=NOW) == "1 minute ago"


def test_humandate_hours() -> None:
    assert humandate((NOW - timedelta(hours=3)).isoformat(), now=NOW) == "3 hours ago"


def test_humandate_days() -> None:
    assert humandate((NOW - timedelta(days=2)).isoformat(), now=NOW) == "2 days ago"


def test_humandate_absolute_for_old() -> None:
    old = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    assert humandate(old.isoformat(), now=NOW) == "Jan 05, 2026"


def test_humandate_z_suffix() -> None:
    assert humandate("2026-06-12T11:00:00Z", now=NOW) == "1 hour ago"


def test_humandate_naive_assumed_utc() -> None:
    assert humandate("2026-06-12T09:00:00", now=NOW) == "3 hours ago"


def test_humandate_epoch_seconds() -> None:
    ts = (NOW - timedelta(hours=2)).timestamp()
    assert humandate(ts, now=NOW) == "2 hours ago"


def test_humandate_unparseable_passthrough() -> None:
    # Legacy/seeded values that aren't full ISO timestamps render unchanged.
    assert humandate("2025", now=NOW) == "2025"
    assert humandate("not a date", now=NOW) == "not a date"
