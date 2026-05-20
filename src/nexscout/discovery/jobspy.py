"""JobSpy discovery engine.

Iterates the cartesian product of profile queries × locations across each
configured board, special-casing Glassdoor + LinkedIn description fetching
per §8.1. Salary formatting, location accept/reject and idempotent inserts
included.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import UTC, datetime
from typing import Any

from ..core.database import insert_jobs
from ..core.profile import Profile

log = logging.getLogger(__name__)

RETRYABLE_RE = re.compile(r"timeout|429|proxy|connection|reset|refused", re.IGNORECASE)
REMOTE_TOKENS = ("remote", "anywhere", "work from home", "wfh", "distributed")
DEFAULT_RESULTS_PER_SITE = 100
MAX_RETRIES = 2


def _format_salary(row: dict[str, Any]) -> str | None:
    cur = row.get("currency") or row.get("salary_currency") or "$"
    interval = row.get("interval") or row.get("salary_interval") or "yr"
    lo = row.get("min_amount") or row.get("salary_min")
    hi = row.get("max_amount") or row.get("salary_max")
    if lo is None and hi is None:
        return None
    try:
        if lo is not None and hi is not None:
            return f"{cur}{int(lo):,}-{cur}{int(hi):,}/{interval}"
        only = lo if lo is not None else hi
        return f"{cur}{int(only):,}/{interval}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def location_passes(
    location: str | None,
    *,
    accept: list[str] | None = None,
    reject_non_remote: list[str] | None = None,
) -> bool:
    """Profile-aware location filter.

    - Remote signal anywhere → accept.
    - ``accept`` list match → accept.
    - ``reject_non_remote`` list match (and not remote) → reject.
    - Otherwise accept (let the scorer decide).
    """
    if not location:
        return True
    lower = location.lower()
    if any(tok in lower for tok in REMOTE_TOKENS):
        return True
    if accept and any(a.lower() in lower for a in accept):
        return True
    return not (reject_non_remote and any(r.lower() in lower for r in reject_non_remote))


def _is_retryable(exc: Exception) -> bool:
    return bool(RETRYABLE_RE.search(str(exc)))


def _import_scrape_jobs() -> Any:
    try:
        from jobspy import scrape_jobs  # type: ignore[import-not-found]
    except ImportError:
        try:
            from python_jobspy import scrape_jobs  # type: ignore[import-not-found]
        except ImportError as e2:
            raise ImportError(
                "python-jobspy not installed; run `pip install --no-deps python-jobspy && "
                "pip install pydantic tls-client requests markdownify regex`"
            ) from e2
    return scrape_jobs


def _scrape_with_retry(boards: list[str], **kwargs: Any) -> Any:
    scrape_jobs = _import_scrape_jobs()
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return scrape_jobs(site_name=boards, **kwargs)
        except Exception as e:
            last_err = e
            if not _is_retryable(e) or attempt == MAX_RETRIES:
                raise
            wait = 5.0 * (attempt + 1)
            log.warning("jobspy attempt %d failed (%s); sleeping %.1fs", attempt + 1, e, wait)
            time.sleep(wait)
    if last_err:
        raise last_err
    return None


def _df_iter(df: Any) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        return list(df.fillna(value="").to_dict(orient="records"))  # type: ignore[no-any-return]
    except AttributeError:
        if isinstance(df, list):
            return df
        return []


def _build_rows(
    records: list[dict[str, Any]],
    *,
    profile: Profile,
    discovered_at: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in records:
        url = r.get("job_url") or r.get("url")
        if not url:
            continue
        loc = r.get("location") or ""
        if not location_passes(
            loc,
            accept=profile.search.location_accept,
            reject_non_remote=profile.search.location_reject_non_remote,
        ):
            continue
        description = r.get("description") or ""
        full_desc = description if len(description) >= 200 else None
        row: dict[str, Any] = {
            "url": url,
            "title": r.get("title") or "",
            "salary": _format_salary(r),
            "description": description[:2000] if description else None,
            "location": loc,
            "site": r.get("site") or r.get("source") or "jobspy",
            "strategy": "jobspy",
            "discovered_at": discovered_at,
        }
        if full_desc:
            row["full_description"] = full_desc
            row["detail_scraped_at"] = discovered_at
        out.append(row)
    return out


def run_jobspy(
    profile: Profile,
    *,
    conn: sqlite3.Connection,
    country_indeed: str = "usa",
) -> tuple[int, int]:
    """Run the JobSpy engine. Returns ``(new_count, duplicate_count)``."""
    boards_cfg = list(profile.search.boards.jobspy or [])
    if not boards_cfg:
        return 0, 0
    results_per_site = profile.search.boards.jobspy.__len__() and (
        getattr(profile.search.boards, "jobspy_results_per_site", None) or DEFAULT_RESULTS_PER_SITE
    )
    glassdoor = "glassdoor" in boards_cfg
    boards_minus_glassdoor = [b for b in boards_cfg if b != "glassdoor"]
    linkedin = "linkedin" in boards_minus_glassdoor

    new_total = 0
    dup_total = 0
    now = datetime.now(UTC).isoformat()

    for q in profile.search.queries:
        for loc in profile.search.locations:
            base_kwargs: dict[str, Any] = {
                "search_term": q.q,
                "location": loc.q,
                "results_wanted": results_per_site,
                "hours_old": profile.search.hours_old,
                "description_format": "markdown",
                "country_indeed": country_indeed,
                "is_remote": loc.remote,
            }
            if linkedin:
                base_kwargs["linkedin_fetch_description"] = True

            try:
                df = _scrape_with_retry(boards_minus_glassdoor, **base_kwargs) if boards_minus_glassdoor else None
            except Exception as e:
                log.warning("jobspy main pull failed for (%s, %s): %s", q.q, loc.label, e)
                df = None

            gdf = None
            if glassdoor:
                gd_kwargs = dict(base_kwargs)
                gd_kwargs["location"] = (loc.q.split(",")[0] or loc.q).strip()
                try:
                    gdf = _scrape_with_retry(["glassdoor"], **gd_kwargs)
                except Exception as e:
                    log.warning("jobspy glassdoor failed for (%s, %s): %s", q.q, loc.label, e)

            records = _df_iter(df) + _df_iter(gdf)
            rows = _build_rows(records, profile=profile, discovered_at=now)
            if not rows:
                continue
            new_count, dup_count = insert_jobs(rows, conn=conn)
            new_total += new_count
            dup_total += dup_count
    return new_total, dup_total
