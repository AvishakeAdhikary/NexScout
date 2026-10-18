"""All source providers, URL auto-detection, and the built-in catalog."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from nexscout.integrations.sources.ats import PROVIDERS as ATS
from nexscout.integrations.sources.boards import PROVIDERS as BOARDS
from nexscout.integrations.sources.core import Entry, Http, Provider, SourceError

PROVIDERS: dict[str, Provider] = {**ATS, **BOARDS}
ATS_LINK = re.compile(
    r"https://(?:job-boards(?:\.eu)?\.greenhouse\.io|boards(?:\.eu)?\.greenhouse\.io|"
    r"jobs(?:\.eu)?\.lever\.co|jobs\.ashbyhq\.com|apply\.workable\.com|"
    r"(?:careers|jobs)\.smartrecruiters\.com|[a-z0-9-]+\.recruitee\.com|"
    r"[a-z0-9-]+\.jobs\.personio\.(?:de|com)|[a-z0-9-]+\.teamtailor\.com|"
    r"[a-z0-9-]+\.breezy\.hr|[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com/[^\s\"'<>]*|"
    r"ats\.rippling\.com)/[A-Za-z0-9_.-]+",
    re.I,
)
GENERIC = ("feed", "jsonld")


def _detect_order() -> list[str]:
    """Specific ATS/boards first (registration order), the generic feed last; JSON-LD pages are
    only chosen by probing."""
    return [*(k for k in PROVIDERS if k not in GENERIC), "feed"]


def detect_provider(url: str) -> tuple[str, dict[str, Any]] | None:
    """The provider for a pasted address, like career-ops' detect(): first match wins."""
    if not url or not url.strip():
        return None
    for pid in _detect_order():
        cfg = PROVIDERS[pid].detect(url.strip())
        if cfg is not None:
            return pid, dict(cfg)
    return None


async def probe(url: str, name: str = "") -> tuple[str, dict[str, Any], int]:
    """Find a provider that can read `url` and how many postings it sees now. Unknown pages are
    tried as a feed (via <link rel="alternate">) and then as schema.org JobPosting data."""
    found = detect_provider(url)
    http = Http()
    if found is not None:
        pid, cfg = found
        jobs = await PROVIDERS[pid].fetch(
            http, Entry(key="probe", provider=pid, name=name, url=url, config=cfg)
        )
        return pid, cfg, len(jobs)
    page = await http.text(url, robots=True, accept="text/html")

    # A branded careers page usually embeds or links its ATS board (career-ops "discover").
    for m in ATS_LINK.finditer(page):
        found = detect_provider(m.group(0))
        if found is not None:
            pid, cfg = found
            try:
                jobs = await PROVIDERS[pid].fetch(
                    http, Entry(key="probe", provider=pid, name=name, url=m.group(0), config=cfg)
                )
            except SourceError:
                continue
            if jobs:
                return pid, cfg, len(jobs)
    feed = re.search(
        r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', page, re.I
    )
    if feed:
        from urllib.parse import urljoin

        feed_url = urljoin(url, feed.group(1))
        jobs = await PROVIDERS["feed"].fetch(
            http,
            Entry(key="probe", provider="feed", name=name, url=feed_url, config={"feed": feed_url}),
        )
        if jobs:
            return "feed", {"feed": feed_url}, len(jobs)
    try:
        jobs = await PROVIDERS["jsonld"].fetch(
            http, Entry(key="probe", provider="jsonld", name=name, url=url)
        )
        return "jsonld", {}, len(jobs)
    except SourceError as exc:
        raise SourceError(
            "NexScout can't read postings from this address: it isn't a supported job board, "
            "has no job feed, and publishes no JobPosting data. You can still add positions "
            "by hand."
        ) from exc


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    raw = (
        resources.files("nexscout.integrations.sources").joinpath("catalog.yaml").read_text("utf-8")
    )
    data: dict[str, Any] = yaml.safe_load(raw)
    return data


def catalog_entries() -> dict[str, Entry]:
    out: dict[str, Entry] = {}
    for e in catalog().get("entries") or []:
        if e.get("provider") not in PROVIDERS:
            continue
        out[e["key"]] = Entry(
            key=e["key"],
            provider=e["provider"],
            name=e["name"],
            url=e.get("url") or "",
            config=dict(e.get("config") or {}),
            countries=list(e.get("countries") or []),
            kinds=list(e.get("kinds") or ["job"]),
            category=e.get("category") or "company",
        )
    return out
