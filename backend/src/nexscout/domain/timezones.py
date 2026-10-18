"""IANA time zones for date-only things the user sees ("due today" means the user's today)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "UTC"


@lru_cache(maxsize=512)
def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def valid_timezone(name: str | None) -> str | None:
    """The name if it is a real IANA zone ("Europe/Helsinki"), else None."""
    if not name or len(name) > 64 or name.startswith(("/", ".")) or ".." in name:
        return None
    return name if _zone(name) is not None else None


def local_today(now: datetime, tz: str | None) -> date:
    """The calendar date at `now` in zone `tz` (unknown zones count as UTC)."""
    zone = _zone(tz) if tz and valid_timezone(tz) else None
    return now.astimezone(zone or UTC).date()
