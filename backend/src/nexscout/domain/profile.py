"""Candidate profile facts: typed section schemas, provenance status, and completeness rules.

A *fact* is one structured claim about the candidate (an education entry, a job, a skill, ...).
Every fact records how it was obtained (`FactStatus`) and whether the user reviewed it
(`ReviewState`). Only accepted facts may feed matching or document generation (AGENTS.md §3).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from nexscout.domain.errors import ValidationFailed


class Section(StrEnum):
    SUMMARY = "summary"
    EDUCATION = "education"
    EMPLOYMENT = "employment"
    RESEARCH = "research"
    PUBLICATION = "publication"
    PROJECT = "project"
    SKILL = "skill"
    CERTIFICATION = "certification"
    AWARD = "award"
    PATENT = "patent"
    VOLUNTEER = "volunteer"
    LEADERSHIP = "leadership"
    MEMBERSHIP = "membership"  # professional affiliations / associations
    REFERENCE = "reference"
    OTHER = "other"


class FactStatus(StrEnum):
    """How we know this. Inferred is never treated as a verified personal fact."""

    USER_ENTERED = "user_entered"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    VERIFIED = "verified"
    EXTERNAL = "external"


class ReviewState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# "2021", "2021-09", "2021-09-30", or "present" (end dates only). Partial dates are normal in CVs.
_PARTIAL_DATE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")
PRESENT = "present"


def check_partial_date(value: str | None, *, allow_present: bool) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if allow_present and v == PRESENT:
        return PRESENT
    if not _PARTIAL_DATE.match(v):
        raise ValueError(
            "Use YYYY, YYYY-MM, or YYYY-MM-DD" + (" or 'present'" if allow_present else "")
        )
    return v


Text = Annotated[str, Field(min_length=1, max_length=500)]
OptText = Annotated[str | None, Field(default=None, max_length=500)]
LongText = Annotated[str | None, Field(default=None, max_length=5000)]
Url = Annotated[str | None, Field(default=None, max_length=2048)]


class FactData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Dated(FactData):
    start: str | None = None
    end: str | None = None

    @field_validator("start")
    @classmethod
    def _start(cls, v: str | None) -> str | None:
        return check_partial_date(v, allow_present=False)

    @field_validator("end")
    @classmethod
    def _end(cls, v: str | None) -> str | None:
        return check_partial_date(v, allow_present=True)


class SummaryData(FactData):
    text: Annotated[str, Field(min_length=1, max_length=5000)]


class EducationData(_Dated):
    institution: Text
    degree: OptText = None
    field_of_study: OptText = None
    grade: OptText = None
    location: OptText = None
    description: LongText = None


class EmploymentData(_Dated):
    organization: Text
    title: Text
    employment_type: OptText = None
    location: OptText = None
    description: LongText = None


class ResearchData(_Dated):
    title: Text
    organization: OptText = None
    role: OptText = None
    description: LongText = None


class PublicationData(FactData):
    title: Text
    authors: OptText = None
    venue: OptText = None
    year: str | None = None
    doi: OptText = None
    url: Url = None

    @field_validator("year")
    @classmethod
    def _year(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        if not re.fullmatch(r"\d{4}", v.strip()):
            raise ValueError("Year must be YYYY")
        return v.strip()


class ProjectData(_Dated):
    name: Text
    role: OptText = None
    description: LongText = None
    url: Url = None
    technologies: list[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=50
    )


class SkillData(FactData):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    category: OptText = None
    level: OptText = None


class CertificationData(FactData):
    name: Text
    issuer: OptText = None
    date: str | None = None
    expires: str | None = None
    credential_id: OptText = None
    url: Url = None

    @field_validator("date", "expires")
    @classmethod
    def _dates(cls, v: str | None) -> str | None:
        return check_partial_date(v, allow_present=False)


class AwardData(FactData):
    name: Text
    issuer: OptText = None
    date: str | None = None
    description: LongText = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return check_partial_date(v, allow_present=False)


class PatentData(FactData):
    title: Text
    number: OptText = None
    office: OptText = None
    date: str | None = None
    status: OptText = None

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        return check_partial_date(v, allow_present=False)


class RoleAtOrgData(_Dated):
    organization: Text
    role: OptText = None
    description: LongText = None


class ReferenceData(FactData):
    name: Text
    relationship: OptText = None
    organization: OptText = None
    contact: OptText = None  # private by default (see default_private)


class OtherData(FactData):
    title: Text
    description: LongText = None


SECTION_SCHEMAS: dict[Section, type[FactData]] = {
    Section.SUMMARY: SummaryData,
    Section.EDUCATION: EducationData,
    Section.EMPLOYMENT: EmploymentData,
    Section.RESEARCH: ResearchData,
    Section.PUBLICATION: PublicationData,
    Section.PROJECT: ProjectData,
    Section.SKILL: SkillData,
    Section.CERTIFICATION: CertificationData,
    Section.AWARD: AwardData,
    Section.PATENT: PatentData,
    Section.VOLUNTEER: RoleAtOrgData,
    Section.LEADERSHIP: RoleAtOrgData,
    Section.MEMBERSHIP: RoleAtOrgData,
    Section.REFERENCE: ReferenceData,
    Section.OTHER: OtherData,
}

# Sections whose facts are private unless the user decides otherwise.
PRIVATE_BY_DEFAULT: frozenset[Section] = frozenset({Section.REFERENCE})


def validate_fact_data(section: Section, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize `data` for `section`. Returns a JSON-safe dict."""
    schema = SECTION_SCHEMAS[section]
    try:
        model = schema.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'data'}: {err['msg']}"
            for err in exc.errors()
        )
        raise ValidationFailed(f"Invalid {section.value} entry: {details}") from exc
    dumped: dict[str, Any] = model.model_dump(mode="json", exclude_none=True)
    return dumped


def fact_label(section: Section, data: dict[str, Any]) -> str:
    """Short human label for lists, mind-map nodes, and review screens."""
    match section:
        case Section.EDUCATION:
            parts = [data.get("degree"), data.get("field_of_study")]
            head = ", ".join(p for p in parts if p)
            return f"{head} at {data['institution']}" if head else str(data["institution"])
        case Section.EMPLOYMENT:
            return f"{data['title']} at {data['organization']}"
        case Section.SUMMARY:
            text = str(data["text"])
            return text if len(text) <= 80 else text[:77] + "..."
        case Section.SKILL:
            return str(data["name"])
        case Section.VOLUNTEER | Section.LEADERSHIP | Section.MEMBERSHIP:
            role = data.get("role")
            return f"{role} at {data['organization']}" if role else str(data["organization"])
        case Section.PROJECT | Section.CERTIFICATION | Section.AWARD | Section.REFERENCE:
            return str(data["name"])
        case _:
            return str(data.get("title") or data.get("name") or section.value)


# ------------------------------------------------------------------- completeness / gaps
class Gap(BaseModel):
    """A piece of missing information the user may want to fill in."""

    code: str
    section: Section
    message: str
    fact_id: str | None = None


def find_gaps(facts: list[tuple[str, Section, dict[str, Any]]]) -> list[Gap]:
    """Deterministic missing-information checks over *accepted* facts.

    `facts` is (fact_id, section, data). No model inference is involved.
    """
    gaps: list[Gap] = []
    by_section: dict[Section, list[tuple[str, dict[str, Any]]]] = {}
    for fid, section, data in facts:
        by_section.setdefault(section, []).append((fid, data))

    if Section.SUMMARY not in by_section:
        gaps.append(
            Gap(
                code="missing_summary",
                section=Section.SUMMARY,
                message="Add a short professional summary in your own words.",
            )
        )
    if Section.EDUCATION not in by_section:
        gaps.append(
            Gap(
                code="missing_education",
                section=Section.EDUCATION,
                message="No education entries yet.",
            )
        )
    if Section.SKILL not in by_section:
        gaps.append(
            Gap(code="missing_skills", section=Section.SKILL, message="No skills listed yet.")
        )
    if Section.EMPLOYMENT not in by_section and Section.RESEARCH not in by_section:
        gaps.append(
            Gap(
                code="missing_experience",
                section=Section.EMPLOYMENT,
                message="No work or research experience yet. Add it if you have any.",
            )
        )

    for section in (Section.EDUCATION, Section.EMPLOYMENT, Section.RESEARCH):
        for fid, data in by_section.get(section, []):
            if not data.get("start") and not data.get("end"):
                gaps.append(
                    Gap(
                        code="missing_dates",
                        section=section,
                        fact_id=fid,
                        message=f"Add dates for: {fact_label(section, data)}.",
                    )
                )
            start, end = data.get("start"), data.get("end")
            if start and end and end != PRESENT and end < start:
                gaps.append(
                    Gap(
                        code="end_before_start",
                        section=section,
                        fact_id=fid,
                        message=f"End date is before start date: {fact_label(section, data)}.",
                    )
                )
    for fid, data in by_section.get(Section.EDUCATION, []):
        if not data.get("degree"):
            gaps.append(
                Gap(
                    code="missing_degree",
                    section=Section.EDUCATION,
                    fact_id=fid,
                    message=f"Which degree or qualification? ({data['institution']})",
                )
            )
    return gaps
