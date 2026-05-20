"""Workday CXS-API discovery engine (§8.2)."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import time
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

import httpx
import yaml

from ..core.config import employers_path
from ..core.database import insert_jobs
from ..core.profile import Profile
from .jobspy import location_passes

log = logging.getLogger(__name__)

MAX_PAGES = 25
PAGE_SIZE = 20
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (NexScout/0.1.0)",
}


def _load_packaged_employers() -> dict[str, Any]:
    pkg = resources.files("nexscout.discovery") / "employers.yaml"
    return yaml.safe_load(pkg.read_text(encoding="utf-8")) or {}


def ship_default_employers(dest: Path | None = None) -> Path:
    """On first run, copy the packaged ``employers.yaml`` to ``~/.nexscout/``."""
    target = dest or employers_path()
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    pkg = resources.files("nexscout.discovery") / "employers.yaml"
    with resources.as_file(pkg) as src:
        shutil.copyfile(src, target)
    return target


def load_employers(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Read the employer registry; falls back to the packaged default."""
    p = path or employers_path()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {} if p.exists() else _load_packaged_employers()
    employers = data.get("employers") or {}
    if not isinstance(employers, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for slug, entry in employers.items():
        if isinstance(entry, dict):
            out[slug] = entry
    return out


_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    text = _TAG_RE.sub("", html or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _build_client(profile: Profile, timeout: float = 30.0) -> httpx.Client:
    proxy = profile.proxy
    proxies: str | None = None
    if proxy:
        # Accept "host:port" or "host:port:user:pass".
        parts = proxy.split(":")
        if len(parts) == 4:
            host, port, user, pw = parts
            proxies = f"http://{user}:{pw}@{host}:{port}"
        elif len(parts) == 2:
            proxies = f"http://{parts[0]}:{parts[1]}"
    if proxies:
        return httpx.Client(timeout=timeout, headers=HEADERS, proxy=proxies)
    return httpx.Client(timeout=timeout, headers=HEADERS)


def _search_page(
    client: httpx.Client,
    *,
    base_url: str,
    tenant: str,
    site_id: str,
    query: str,
    offset: int,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/wday/cxs/{tenant}/{site_id}/jobs"
    body = {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": query}
    resp = client.post(url, json=body)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _fetch_detail(
    client: httpx.Client, *, base_url: str, tenant: str, site_id: str, external_path: str
) -> dict[str, Any] | None:
    if not external_path:
        return None
    if not external_path.startswith("/"):
        external_path = "/" + external_path
    url = f"{base_url.rstrip('/')}/wday/cxs/{tenant}/{site_id}{external_path}"
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
    except httpx.HTTPError as e:
        log.warning("workday detail failed: %s (%s)", url, e)
        return None


def run_workday(
    profile: Profile,
    *,
    conn: sqlite3.Connection,
    employers_yaml: Path | None = None,
    max_pages: int = MAX_PAGES,
) -> tuple[int, int]:
    """Run the Workday engine. Returns ``(new, duplicate)``."""
    ship_default_employers()
    employers = load_employers(employers_yaml)
    if not employers:
        return 0, 0

    queries = [q.q for q in profile.search.queries if q.tier <= profile.search.workday_max_tier]
    if not queries:
        return 0, 0

    new_total = 0
    dup_total = 0
    now = datetime.now(UTC).isoformat()
    rows_buffer: list[dict[str, Any]] = []

    with _build_client(profile) as client:
        for _slug, emp in employers.items():
            base_url = str(emp.get("base_url", "")).rstrip("/")
            tenant = str(emp.get("tenant", ""))
            site_id = str(emp.get("site_id", ""))
            name = str(emp.get("name", _slug))
            if not (base_url and tenant and site_id):
                continue
            for query in queries:
                fetched = 0
                for page in range(max_pages):
                    offset = page * PAGE_SIZE
                    try:
                        data = _search_page(
                            client, base_url=base_url, tenant=tenant, site_id=site_id, query=query, offset=offset
                        )
                    except httpx.HTTPError as e:
                        log.warning("workday search failed %s (%s): %s", name, query, e)
                        break
                    postings = data.get("jobPostings") or []
                    total = int(data.get("total") or 0)
                    if not postings:
                        break
                    for post in postings:
                        external_path = post.get("externalPath") or ""
                        location = post.get("locationsText") or ""
                        if not location_passes(
                            location,
                            accept=profile.search.location_accept,
                            reject_non_remote=profile.search.location_reject_non_remote,
                        ):
                            continue
                        detail = _fetch_detail(
                            client,
                            base_url=base_url,
                            tenant=tenant,
                            site_id=site_id,
                            external_path=external_path,
                        )
                        info = (detail or {}).get("jobPostingInfo") or {}
                        full = _strip_html(info.get("jobDescription") or "")
                        application_url = info.get("externalUrl") or post.get("externalUrl") or ""
                        url = application_url or f"{base_url}{external_path}"
                        row: dict[str, Any] = {
                            "url": url,
                            "title": post.get("title") or info.get("title") or "",
                            "salary": None,
                            "description": (full[:2000] if full else None),
                            "location": location,
                            "site": name,
                            "strategy": "workday_api",
                            "discovered_at": now,
                            "application_url": application_url or None,
                        }
                        if full:
                            row["full_description"] = full
                            row["detail_scraped_at"] = now
                        rows_buffer.append(row)
                    fetched += len(postings)
                    if fetched >= total:
                        break
                    time.sleep(0.5)  # politeness
                if rows_buffer:
                    new_count, dup_count = insert_jobs(rows_buffer, conn=conn)
                    new_total += new_count
                    dup_total += dup_count
                    rows_buffer = []
    return new_total, dup_total
