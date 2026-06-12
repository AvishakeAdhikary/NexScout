"""Jinja template filters for the web UI.

Currently just :func:`humandate`, which turns the ISO-8601 timestamps NexScout
stores (e.g. ``2026-06-12T03:00:14.067+00:00``) into something a human reads at
a glance — a relative phrase for recent times ("3 hours ago") and a plain
calendar date for older ones ("Jun 12, 2026"). Anything it can't parse is
returned unchanged, so seeded/legacy values never break a page render.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _parse(value: Any) -> datetime | None:
    """Best-effort parse of a stored timestamp into an aware datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        # datetime.fromisoformat (3.11) handles offsets but not a trailing 'Z'.
        normalised = (s[:-1] + "+00:00") if s.endswith("Z") else s
        try:
            return datetime.fromisoformat(normalised)
        except ValueError:
            return None
    return None


def humandate(value: Any, *, now: datetime | None = None) -> str:
    """Render a stored timestamp in friendly form.

    ``now`` is injectable for deterministic tests.
    """
    if value is None or value == "":
        return ""
    dt = _parse(value)
    if dt is None:
        return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    current = now or datetime.now(UTC)
    secs = (current - dt).total_seconds()

    if 0 <= secs < 60:
        return "just now"
    if 0 <= secs < 3600:
        n = int(secs // 60)
        return f"{n} minute{'s' if n != 1 else ''} ago"
    if 0 <= secs < 86400:
        n = int(secs // 3600)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    if 0 <= secs < 7 * 86400:
        n = int(secs // 86400)
        return f"{n} day{'s' if n != 1 else ''} ago"
    # Older than a week (or a future date): show the calendar date.
    return dt.strftime("%b %d, %Y")


__all__ = ["humandate"]
