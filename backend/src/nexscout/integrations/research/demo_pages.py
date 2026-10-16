"""Bundled demo web pages for the demo academic listings (clearly labelled demo data).

Addresses on reserved `.example` hosts (RFC 2606) can never be real, so research never sends them
to the network. If a demo page exists it is served from here, otherwise the source is skipped.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from nexscout.domain.opportunities import canonicalize_url

_FILE = Path(__file__).parent / "fixtures" / "demo_pages.json"


def is_reserved_demo_host(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "example" or host.endswith(".example")


@lru_cache(maxsize=1)
def _pages() -> dict[str, dict[str, str]]:
    raw: dict[str, dict[str, str]] = json.loads(_FILE.read_text(encoding="utf-8"))["pages"]
    return {canonicalize_url(url) or url: page for url, page in raw.items()}


def demo_page(url: str) -> tuple[str, str] | None:
    """(title, html) for a demo address, or None."""
    page = _pages().get(canonicalize_url(url) or url)
    return (page["title"], page["html"]) if page else None
