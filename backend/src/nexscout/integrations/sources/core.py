"""Real opportunity sources: the provider framework (ADR-0015).

A *provider* knows one kind of public source: an applicant-tracking system's public job-board API
(Greenhouse, Lever, Ashby, …), a job board's public API or feed, or a generic RSS/JSON-LD page.
A *source entry* is one configured instance (a company's board, a board with a country filter),
from the built-in catalog or added by the user. `EntryAdapter` turns an entry into the existing
`SourceAdapter` contract, so sync, dedup and matching are unchanged.

Provider logic is ported from career-ops (MIT, github.com/career-ops-hq/career-ops; see
THIRD_PARTY_NOTICES.md) and runs through NexScout's SSRF-safe fetcher: public addresses only,
per-host pacing, size caps, and robots.txt for pages that aren't official public APIs.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from nexscout.domain.geo import resolve_location
from nexscout.domain.opportunities import NormalizedOpportunity, OpportunityKind, Remote
from nexscout.domain.signals import read_signals
from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed, SafeFetcher
from nexscout.integrations.sources.base import (
    SourceCapabilities,
    SourcePage,
    SourceQuery,
    SourceSettings,
)

USER_AGENT = (
    "NexScout/2 (personal job-search assistant; +https://github.com/AvishakeAdhikary/NexScout)"
)
MAX_JOBS_PER_SOURCE = 2000
MAX_PAGES = 25


class SourceError(Exception):
    """A source couldn't be read. The message is shown to the user."""


@dataclass
class Job:
    """One posting as a provider reads it (mirrors career-ops' Job shape)."""

    title: str
    url: str
    company: str = ""
    location: str = ""
    description: str = ""
    posted_at: str | None = None  # ISO date
    closes_at: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    external_id: str | None = None
    requisition_id: str | None = None
    remote: bool | None = None
    employment_type: str | None = None
    kind: str | None = None  # phd | postdoc | job … when the source says so
    country: str | None = None  # ISO code when the source gives one


@dataclass
class Entry:
    key: str  # "greenhouse:anthropic"
    provider: str
    name: str
    url: str = ""
    api: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    countries: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=lambda: ["job"])
    category: str = "company"  # company | board | academic | feed
    notes: str = ""


class Http:
    """What providers may use to talk to the network."""

    def __init__(self, fetcher: SafeFetcher | None = None) -> None:
        self.fetcher = fetcher or SafeFetcher(
            user_agent=USER_AGENT,
            respect_robots=False,
            max_bytes=15 * 1024 * 1024,
            timeout_s=30.0,
            min_interval_s=0.5,
        )
        self.requests = 0

    async def _call(
        self,
        method: str,
        url: str,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        robots: bool = False,
        accept: str = "application/json",
    ) -> tuple[int, bytes, str]:
        self.requests += 1
        if self.requests > 400:
            raise SourceError("This source needed too many requests; stopped to stay polite.")
        hdrs = {"Accept": accept, **(headers or {})}
        content = None
        if body is not None:
            content = json.dumps(body).encode() if not isinstance(body, bytes) else body
            hdrs.setdefault("Content-Type", "application/json")
        try:
            status, _h, data, final = await self.fetcher.request(
                method, url, content=content, headers=hdrs, check_robots=robots
            )
        except FetchBlocked as exc:
            raise SourceError(str(exc)) from exc
        except FetchFailed as exc:
            raise SourceError(str(exc)) from exc
        if status == 404:
            raise SourceError("The source says this board doesn't exist (HTTP 404).")
        if status == 429:
            raise SourceError("The source asked us to slow down (HTTP 429). Try again later.")
        if status >= 400:
            raise SourceError(f"The source answered with HTTP {status}.")
        return status, data, final

    async def json(
        self,
        url: str,
        *,
        method: str = "GET",
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        _, data, _ = await self._call(method, url, body=body, headers=headers)
        try:
            return json.loads(data)
        except ValueError as exc:
            raise SourceError("The source didn't return valid JSON.") from exc

    async def text(
        self,
        url: str,
        *,
        robots: bool = False,
        accept: str = "*/*",
        headers: dict[str, str] | None = None,
    ) -> str:
        _, data, _ = await self._call("GET", url, robots=robots, accept=accept, headers=headers)
        return data.decode("utf-8", errors="replace")


class Provider(Protocol):
    id: str
    label: str
    category: str  # ats | board | academic | feed
    terms: str

    def detect(self, url: str) -> dict[str, Any] | None: ...

    async def fetch(self, http: Http, entry: Entry) -> list[Job]: ...


# --- helpers shared by providers --------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|li|ul|ol|br|h[1-6]|tr|section|article)\b[^>]*>", re.I)
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)


def html_to_text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    s = html.unescape(value) if "&lt;" in value else value
    s = _SCRIPT.sub(" ", s)
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    lines = [" ".join(line.split()) for line in s.splitlines()]
    return "\n".join(line for line in lines if line)[:50_000]


def https_url(value: Any, hosts: set[str] | None = None) -> str:
    """An https URL (optionally on one of `hosts`), else ""."""
    if not isinstance(value, str) or not value.strip():
        return ""
    v = value.strip()
    p = urlsplit(v)
    if p.scheme != "https" or not p.hostname:
        return ""
    if (
        hosts
        and p.hostname.lower() not in hosts
        and not any(p.hostname.lower().endswith("." + h) for h in hosts)
    ):
        return ""
    return v


def iso_date(value: Any) -> str | None:
    """Epoch ms/s, ISO strings and RFC 822 dates → YYYY-MM-DD."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(ts, UTC).date().isoformat()
        s = str(value).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(s).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def first(*values: Any) -> str:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def join_loc(*parts: Any) -> str:
    seen: list[str] = []
    for p in parts:
        if isinstance(p, str) and p.strip() and p.strip().lower() not in (s.lower() for s in seen):
            seen.append(p.strip())
    return ", ".join(seen)


def slug_from(url: str, pattern: str) -> str | None:
    m = re.search(pattern, url or "", re.I)
    return m.group(1) if m else None


# --- normalization: Job → NormalizedOpportunity ----------------------------------------------

_PHD = re.compile(
    r"\b(ph\.?\s?d|doctoral|doctorate|väitöskirja|doktorand|doctorant|promovend|stipendiat|"
    r"doktorgrads|tohtorikoulutettava|dottorato|doctorado|"
    r"doctoral researcher|early stage researcher|esr\b|phd student|phd candidate)",
    re.I,
)
_POSTDOC = re.compile(r"\b(post-?doc|postdoctoral|post-doctoral)", re.I)


def detect_kind(job: Job, entry: Entry) -> OpportunityKind:
    if job.kind in {k.value for k in OpportunityKind}:
        return OpportunityKind(job.kind)
    if _POSTDOC.search(job.title):
        return OpportunityKind.POSTDOC
    if _PHD.search(job.title):
        return OpportunityKind.PHD
    if "phd" in entry.kinds and "job" not in entry.kinds:
        return OpportunityKind.PHD
    return OpportunityKind.JOB


def normalize_job(job: Job, entry: Entry) -> NormalizedOpportunity:
    geo = resolve_location(job.location)
    countries = list(geo.countries)
    if job.country and job.country.upper() not in countries:
        countries.insert(0, job.country.upper())
    if not countries and len(entry.countries) == 1:
        countries = [entry.countries[0]]  # a single-country board (e.g. Platsbanken → SE)
    remote = Remote.REMOTE if (job.remote or geo.remote) else Remote.UNKNOWN
    if job.remote is False and not geo.remote:
        remote = Remote.ONSITE if "hybrid" not in job.location.lower() else Remote.HYBRID
    elif "hybrid" in job.location.lower():
        remote = Remote.HYBRID
    signals = read_signals(job.description)
    ext = job.external_id or hashlib.sha256(job.url.encode()).hexdigest()[:32]
    from nexscout.domain.opportunities import Sponsorship

    sponsorship = {"offered": Sponsorship.YES, "refused": Sponsorship.NO}.get(
        signals.sponsorship, Sponsorship.UNKNOWN
    )
    return NormalizedOpportunity(
        source_key=entry.key,
        external_id=str(ext)[:300],
        source_url=job.url[:2048],
        kind=detect_kind(job, entry),
        title=job.title[:300] or "Untitled position",
        organization_name=(job.company or entry.name)[:300],
        location_city=None,
        location_country=countries[0] if countries else None,
        country_codes=countries,
        location_text=job.location[:300] or None,
        remote_scope=geo.remote_scope,
        remote=remote,
        employment_type=job.employment_type,
        salary_min=int(job.salary_min) if job.salary_min is not None else None,
        salary_max=int(job.salary_max) if job.salary_max is not None else None,
        salary_currency=job.salary_currency,
        salary_period="year" if job.salary_min or job.salary_max else None,
        funding=signals.funding if signals.funding != "not_stated" else None,
        sponsorship=sponsorship,
        posted_at=date.fromisoformat(job.posted_at) if job.posted_at else None,
        closes_at=date.fromisoformat(job.closes_at) if job.closes_at else None,
        canonical_url=job.url[:2048],
        requisition_id=job.requisition_id,
        description=job.description[:50_000],
        application_method="online",
    )


class EntryAdapter:
    """A configured source entry as a `SourceAdapter` (fetches everything in one page)."""

    def __init__(self, entry: Entry, provider: Provider, http_factory: Any = None) -> None:
        self.entry = entry
        self.provider = provider
        self.key = entry.key
        self.name = entry.name
        kinds = frozenset(
            OpportunityKind(k) for k in entry.kinds if k in OpportunityKind._value2member_map_
        )
        if "phd" in entry.kinds:
            kinds = kinds | {
                OpportunityKind.PHD,
                OpportunityKind.POSTDOC,
                OpportunityKind.RESEARCH_ASSISTANT,
            }
        self.capabilities = SourceCapabilities(
            kinds=kinds or frozenset({OpportunityKind.JOB}),
            supports_keywords=False,
            supports_location=False,
            pagination="none",
            auth="none",
            rate_limit="paced (≥0.5 s between requests per host)",
            terms=provider.terms,
            incremental="re-reads the board; unchanged postings are skipped by content hash",
            is_demo_data=False,
        )
        self._http_factory = http_factory or Http

    async def fetch(
        self, query: SourceQuery, cursor: str | None, settings: SourceSettings
    ) -> SourcePage:
        entry = self.entry
        if query.keywords and not entry.config.get("keywords"):
            # Sources that search (Platsbanken, Arbeitsagentur, Workday, …) use the case's words.
            entry = replace(entry, config={**entry.config, "keywords": list(query.keywords)})
        jobs = await self.provider.fetch(self._http_factory(), entry)
        records = [asdict(j) for j in jobs[:MAX_JOBS_PER_SOURCE] if j.title and j.url]
        return SourcePage(records=records, next_cursor=None)

    def normalize(self, record: dict[str, Any]) -> NormalizedOpportunity:
        return normalize_job(Job(**record), self.entry)
