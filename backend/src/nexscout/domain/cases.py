"""Candidate case domain rules."""

from __future__ import annotations

from enum import StrEnum

from nexscout.domain.errors import ValidationFailed

MAX_CASE_NAME = 120
MAX_CASE_DESCRIPTION = 2000


class CareerPath(StrEnum):
    UNDECIDED = "undecided"
    PHD = "phd"
    EMPLOYMENT = "employment"
    BOTH = "both"

    @property
    def phd_enabled(self) -> bool:
        return self in (CareerPath.PHD, CareerPath.BOTH)

    @property
    def employment_enabled(self) -> bool:
        return self in (CareerPath.EMPLOYMENT, CareerPath.BOTH)


class CaseStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


def normalize_case_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationFailed("Case name must not be empty.")
    if len(cleaned) > MAX_CASE_NAME:
        raise ValidationFailed(f"Case name must be at most {MAX_CASE_NAME} characters.")
    return cleaned


def normalize_description(description: str | None) -> str | None:
    if description is None:
        return None
    cleaned = description.strip()
    if len(cleaned) > MAX_CASE_DESCRIPTION:
        raise ValidationFailed(f"Description must be at most {MAX_CASE_DESCRIPTION} characters.")
    return cleaned or None
