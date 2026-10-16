"""Per-case search preferences, plus optional, private, sensitive eligibility attributes.

Sensitive attributes are never used for suitability scoring. They may only feed explicit
eligibility checks (e.g. "requires work authorization in X") when the user opts in, and the
basis is always shown to the user (spec §4.2).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ShortStr = Annotated[str, Field(min_length=1, max_length=120)]
ShortList = Annotated[list[ShortStr], Field(default_factory=list, max_length=50)]


class ExperienceMode(StrEnum):
    STRICT = "strict"  # prioritize/restrict to roles whose minimum experience you meet
    FLEXIBLE = "flexible"  # include stretch roles, always disclosing the gap


class Seniority(StrEnum):
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"


EmploymentType = Literal[
    "full_time",
    "part_time",
    "contract",
    "internship",
    "temporary",
    "phd_position",
    "postdoc",
    "research_assistant",
    "fellowship",
]


class SensitiveAttributes(BaseModel):
    """Optional and private by default. Never used for scoring."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    work_authorization: ShortList = Field(
        default_factory=list, description="Countries where you may already work."
    )
    veteran_status: Annotated[str | None, Field(default=None, max_length=120)] = None
    use_for_eligibility: bool = Field(
        default=False,
        description="Allow these answers to be used for explicit eligibility checks only.",
    )


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    countries: ShortList = Field(default_factory=list)
    regions: ShortList = Field(default_factory=list)
    cities: ShortList = Field(default_factory=list)
    remote: Literal["any", "onsite", "hybrid", "remote"] = "any"
    willing_to_relocate: bool | None = None

    research_areas: ShortList = Field(default_factory=list)
    disciplines: ShortList = Field(default_factory=list)
    preferred_institutions: ShortList = Field(default_factory=list)
    preferred_employers: ShortList = Field(default_factory=list)
    job_titles: ShortList = Field(default_factory=list)
    industries: ShortList = Field(default_factory=list)

    employment_types: list[EmploymentType] = Field(default_factory=list, max_length=9)
    seniority: list[Seniority] = Field(default_factory=list, max_length=3)
    experience_mode: ExperienceMode = ExperienceMode.STRICT
    min_years_experience: float | None = Field(default=None, ge=0, le=60)
    max_years_experience: float | None = Field(default=None, ge=0, le=60)

    needs_visa_sponsorship: bool | None = None
    funding_required: bool | None = None
    salary_min: int | None = Field(default=None, ge=0, le=10_000_000)
    salary_currency: str | None = None
    earliest_start: str | None = None
    application_horizon_days: int | None = Field(default=None, ge=1, le=730)
    accessibility_notes: Annotated[str | None, Field(default=None, max_length=2000)] = None

    sensitive: SensitiveAttributes = Field(default_factory=SensitiveAttributes)

    @field_validator("salary_currency")
    @classmethod
    def _currency(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", v):
            raise ValueError("Use a 3-letter currency code such as EUR or USD")
        return v

    @field_validator("earliest_start")
    @classmethod
    def _start(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not re.fullmatch(r"\d{4}(-(0[1-9]|1[0-2]))?", v.strip()):
            raise ValueError("Use YYYY or YYYY-MM")
        return v.strip()

    @model_validator(mode="after")
    def _experience_range(self) -> Preferences:
        lo, hi = self.min_years_experience, self.max_years_experience
        if lo is not None and hi is not None and hi < lo:
            raise ValueError("max_years_experience must be at least min_years_experience")
        return self


# ------------------------------------------------------------------- social / profile URLs
class ProfileKind(StrEnum):
    LINKEDIN = "linkedin"
    GITHUB = "github"
    GOOGLE_SCHOLAR = "google_scholar"
    ORCID = "orcid"
    RESEARCHGATE = "researchgate"
    WEBSITE = "website"
    OTHER = "other"


_KIND_BY_HOST: tuple[tuple[str, ProfileKind], ...] = (
    ("linkedin.com", ProfileKind.LINKEDIN),
    ("github.com", ProfileKind.GITHUB),
    ("scholar.google.", ProfileKind.GOOGLE_SCHOLAR),
    ("orcid.org", ProfileKind.ORCID),
    ("researchgate.net", ProfileKind.RESEARCHGATE),
)


def normalize_profile_url(url: str) -> tuple[str, ProfileKind]:
    """Validate a user-supplied profile URL (never fetched here) and classify it."""
    raw = url.strip()
    if not re.match(r"^https?://", raw, re.IGNORECASE):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() not in {"http", "https"} or not host or "." not in host:
        raise ValueError("Enter a full web address, such as https://github.com/yourname")
    if parts.username or parts.password:
        raise ValueError("Links must not contain a username or password")
    if len(raw) > 2048:
        raise ValueError("Link is too long")
    kind = next((k for h, k in _KIND_BY_HOST if h in host), ProfileKind.WEBSITE)
    path = parts.path or "/"
    normalized = f"{parts.scheme.lower()}://{host}{'' if parts.port is None else f':{parts.port}'}"
    normalized += path + (f"?{parts.query}" if parts.query else "")
    return normalized, kind
