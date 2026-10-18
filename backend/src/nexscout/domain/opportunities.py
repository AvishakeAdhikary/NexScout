"""Normalized opportunities, canonicalization, and deterministic deduplication (spec §6.3).

Dedup is decided by explicit rules evaluated in a fixed order. Hard "distinct" guards (different
employer, different requisition ids, different city) win over similarity, so two separate
requisitions are never merged just because their titles look alike. Every decision returns
its reasons, so a merge can be explained and reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from nexscout.domain.mindmap import normalize_org


class OpportunityKind(StrEnum):
    JOB = "job"
    PHD = "phd"
    POSTDOC = "postdoc"
    RESEARCH_ASSISTANT = "research_assistant"
    SCHOLARSHIP = "scholarship"


ACADEMIC_KINDS = frozenset(
    {
        OpportunityKind.PHD,
        OpportunityKind.POSTDOC,
        OpportunityKind.RESEARCH_ASSISTANT,
        OpportunityKind.SCHOLARSHIP,
    }
)


class Remote(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Sponsorship(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


Short = Annotated[str, Field(max_length=300)]


class NormalizedOpportunity(BaseModel):
    """What every source adapter must produce. Unknown values stay None, never guessed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_key: Short
    external_id: Short
    source_url: Annotated[str, Field(max_length=2048)]
    kind: OpportunityKind
    title: Short
    organization_name: Short
    location_city: Short | None = None
    location_region: Short | None = None
    location_country: Short | None = None
    # ISO 3166-1 alpha-2 codes for every place the posting names (first = primary), the
    # source's own location text, and the area a remote role is open to (a group key such as
    # "EU" or "WORLD", or a country code). See domain/geo.py.
    country_codes: list[Annotated[str, Field(min_length=2, max_length=2)]] = Field(
        default_factory=list
    )
    location_text: Short | None = None
    remote_scope: Annotated[str | None, Field(default=None, max_length=20)] = None
    remote: Remote = Remote.UNKNOWN
    employment_type: Short | None = None
    seniority: Short | None = None
    experience_min_years: float | None = Field(default=None, ge=0, le=60)
    experience_max_years: float | None = Field(default=None, ge=0, le=60)
    education_level: Short | None = None  # "bachelor" | "master" | "phd" | ...
    required_skills: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list)
    preferred_skills: list[Annotated[str, Field(max_length=120)]] = Field(default_factory=list)
    research_areas: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: Short | None = None
    salary_period: Short | None = None
    funding: Annotated[str | None, Field(default=None, max_length=2000)] = None
    sponsorship: Sponsorship = Sponsorship.UNKNOWN
    posted_at: date | None = None
    closes_at: date | None = None
    canonical_url: Annotated[str | None, Field(default=None, max_length=2048)] = None
    requisition_id: Short | None = None
    description: Annotated[str, Field(default="", max_length=50_000)] = ""
    application_method: Short | None = None


# ------------------------------------------------------------------------- canonicalization
_TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|gclid|fbclid|msclkid|mc_[a-z]+|ref|referrer|source|src|trk|trackingid|"
    r"_hs\w+|yclid|igshid)$",
    re.IGNORECASE,
)


def canonicalize_url(url: str | None) -> str | None:
    """Stable URL identity: https, lowercase host without www, no tracking params or fragment,
    sorted query, no trailing slash."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.lower().removeprefix("www.")
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not _TRACKING_PARAMS.match(k)
    )
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


_ABBREVIATIONS = {
    "sr": "senior",
    "snr": "senior",
    "jr": "junior",
    "jnr": "junior",
    "eng": "engineer",
    "engr": "engineer",
    "mgr": "manager",
    "mgmt": "management",
    "dev": "developer",
    "swe": "software engineer",
    "sde": "software development engineer",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "nlp": "natural language processing",
    "ds": "data scientist",
    "pm": "product manager",
    "qa": "quality assurance",
    "ra": "research assistant",
    "phd": "phd",
    "postdoc": "postdoctoral",
    "assoc": "associate",
    "asst": "assistant",
    "admin": "administrator",
    "ops": "operations",
    "intl": "international",
    "dept": "department",
    "univ": "university",
}
_ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}


def normalize_title(title: str) -> str:
    text = re.sub(r"\(.*?\)", " ", title.lower())  # drop parentheticals like "(m/f/d)"
    text = re.sub(r"[^\w\s]", " ", text)
    tokens: list[str] = []
    for tok in text.split():
        tok = _ROMAN.get(tok, tok)
        tokens.extend(_ABBREVIATIONS.get(tok, tok).split())
    return " ".join(tokens)


def normalize_location(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.lower())).strip() or None


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def shingles(text: str, k: int = 4) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


# ---------------------------------------------------------------------------------- dedup
@dataclass(frozen=True)
class DedupConfig:
    title_threshold: float = 0.8
    description_threshold: float = 0.5
    max_posted_gap_days: int = 60


DEFAULT_DEDUP = DedupConfig()


@dataclass
class DedupDecision:
    duplicate: bool
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DedupCandidate:
    """The fields dedup needs, from either a new record or a stored opportunity."""

    source_key: str
    external_id: str
    canonical_url: str | None
    employer_key: str
    normalized_title: str
    requisition_id: str | None
    city: str | None
    country: str | None
    description: str
    posted_at: date | None
    kind: str


def candidate_from(opp: NormalizedOpportunity) -> DedupCandidate:
    return DedupCandidate(
        source_key=opp.source_key,
        external_id=opp.external_id,
        canonical_url=canonicalize_url(opp.canonical_url or opp.source_url),
        employer_key=normalize_org(opp.organization_name),
        normalized_title=normalize_title(opp.title),
        requisition_id=(opp.requisition_id or "").strip().lower() or None,
        city=normalize_location(opp.location_city),
        country=normalize_location(opp.location_country),
        description=opp.description,
        posted_at=opp.posted_at,
        kind=opp.kind.value,
    )


def decide(a: DedupCandidate, b: DedupCandidate, cfg: DedupConfig = DEFAULT_DEDUP) -> DedupDecision:
    # 1. Exact identities.
    if a.source_key == b.source_key and a.external_id == b.external_id:
        return DedupDecision(True, 1.0, ["Same source and listing id."])
    if a.canonical_url and a.canonical_url == b.canonical_url:
        return DedupDecision(True, 1.0, ["Same canonical posting URL."])
    # 2. Hard guards: these always mean different opportunities.
    if a.kind != b.kind:
        return DedupDecision(False, 0.0, ["Different opportunity types."])
    if a.employer_key != b.employer_key:
        return DedupDecision(False, 0.0, ["Different employers or institutions."])
    if a.requisition_id and b.requisition_id:
        if a.requisition_id == b.requisition_id:
            return DedupDecision(True, 1.0, ["Same employer and requisition id."])
        return DedupDecision(False, 0.0, ["Different requisition ids at the same employer."])
    if a.city and b.city and a.city != b.city:
        return DedupDecision(False, 0.0, ["Different locations."])
    if a.country and b.country and a.country != b.country:
        return DedupDecision(False, 0.0, ["Different countries."])
    # 3. Similarity, with every threshold required.
    title_sim = jaccard(_tokens(a.normalized_title), _tokens(b.normalized_title))
    desc_sim = jaccard(shingles(a.description), shingles(b.description))
    reasons = [f"Title similarity {title_sim:.2f}", f"Description similarity {desc_sim:.2f}"]
    if a.posted_at and b.posted_at:
        gap = abs((a.posted_at - b.posted_at).days)
        reasons.append(f"Posted {gap} days apart")
        if gap > cfg.max_posted_gap_days:
            return DedupDecision(
                False,
                title_sim * desc_sim,
                [*reasons, "Posted too far apart to be the same listing."],
            )
    score = round(0.5 * title_sim + 0.5 * desc_sim, 3)
    if title_sim >= cfg.title_threshold and desc_sim >= cfg.description_threshold:
        return DedupDecision(
            True, score, ["Same employer, same title, near-identical text.", *reasons]
        )
    return DedupDecision(False, score, reasons)
