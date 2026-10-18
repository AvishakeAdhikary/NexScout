"""Is a newer NexScout release out? (public GitHub releases API, cached for 6 hours).

Only this installation's version and the public release tag are compared; nothing about the
user is sent. Off with NEXSCOUT_UPDATE_CHECK=0. The installed desktop app updates itself
(apps/desktop/src/updates.ts); this check tells zip, server and Docker users.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

from nexscout import __version__
from nexscout.config import Settings
from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed, SafeFetcher

log = structlog.get_logger(__name__)
CACHE_S = 6 * 3600
RETRY_S = 15 * 60  # after a failed check
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    m = _SEMVER.match(value or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


@dataclass(frozen=True)
class Release:
    version: str
    url: str


@dataclass(frozen=True)
class VersionInfo:
    current: str
    latest: str | None
    update_available: bool
    url: str | None
    checked_at: datetime | None


@dataclass
class _Cached:
    at: float
    checked_at: datetime
    release: Release | None


_cache: dict[str, _Cached] = {}
_lock = asyncio.Lock()


async def fetch_latest(repo: str, fetcher: SafeFetcher | None = None) -> Release | None:
    """The latest published release, or None when it can't be read. The response is
    untrusted: only a version-shaped tag and a URL inside this repository are accepted."""
    fetcher = fetcher or SafeFetcher(respect_robots=False, timeout_s=10.0)
    try:
        status, _h, body, _u = await fetcher.request(
            "GET",
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            check_robots=False,
        )
    except (FetchBlocked, FetchFailed) as exc:
        log.info("update_check_failed", error=str(exc))
        return None
    if status != 200:
        log.info("update_check_failed", status=status)
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    tag = data.get("tag_name") if isinstance(data, dict) else None
    url = data.get("html_url") if isinstance(data, dict) else None
    if not isinstance(tag, str) or parse_version(tag) is None:
        return None
    if not isinstance(url, str) or not url.startswith(f"https://github.com/{repo}/releases/"):
        url = f"https://github.com/{repo}/releases/latest"
    return Release(tag.removeprefix("v"), url)


async def version_info(settings: Settings, current: str = __version__) -> VersionInfo:
    if not settings.update_check:
        return VersionInfo(current, None, False, None, None)
    repo = settings.update_repo
    async with _lock:
        hit = _cache.get(repo)
        if hit is None or time.monotonic() - hit.at >= (CACHE_S if hit.release else RETRY_S):
            hit = _Cached(time.monotonic(), datetime.now(UTC), await fetch_latest(repo))
            _cache[repo] = hit
    rel = hit.release
    mine, theirs = parse_version(current), parse_version(rel.version if rel else None)
    newer = bool(mine and theirs and theirs > mine)  # a development build never nags
    return VersionInfo(
        current,
        rel.version if rel else None,
        newer,
        rel.url if rel else None,
        hit.checked_at,
    )
