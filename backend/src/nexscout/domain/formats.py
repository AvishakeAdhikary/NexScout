"""Regional document formats: which conventions a CV, resume or letter should follow.

Applications get rejected for format reasons that have nothing to do with the candidate: a
three-page resume in the US, a German "Lebenslauf" without dates in front, a photo where photos
are discouraged, the wrong paper size. NexScout picks a format from the opportunity's country and
falls back to a widely accepted international format when the location is unknown or isn't
covered.

These are *conventions*, kept deliberately conservative and labelled as such. They never
override what a posting explicitly asks for: posting requirements (e.g. "max. 2 pages") are
checked separately against research findings (domain/compliance.py) and take precedence.
NexScout never adds photos, birth dates, marital status or declarations on the user's behalf.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from nexscout.domain.drafting import DocType

Paper = Literal["A4", "Letter"]
DateStyle = Literal["month_year", "numeric", "year_month"]


@dataclass(frozen=True)
class FormatProfile:
    key: str
    label: str
    paper: Paper
    date_style: DateStyle
    date_first: bool  # entries start with their dates (tabular CVs, e.g. German Lebenslauf)
    page_limits: dict[DocType, int]  # conventional maximums (warnings, not hard rules)
    contact_hint: str
    notes: tuple[str, ...]
    europass_order: bool = False
    signature_line: bool = False  # place, date and name at the end (DACH convention)
    referees_section: bool = False  # Australia/New Zealand convention
    countries: frozenset[str] = field(default_factory=frozenset)


_STD_LIMITS = {
    DocType.RESUME: 2,
    DocType.COVER_LETTER: 1,
    DocType.SOP: 2,
    DocType.REFERRAL_REQUEST: 1,
}

PROFILES: dict[str, FormatProfile] = {
    p.key: p
    for p in (
        FormatProfile(
            key="north_america",
            label="North American (US/Canada)",
            paper="Letter",
            date_style="month_year",
            date_first=False,
            page_limits={**_STD_LIMITS, DocType.RESUME: 2},
            contact_hint="city and state/province, phone, email, LinkedIn (optional)",
            notes=(
                "Resumes are short (one page early in a career, two at most) and US Letter sized.",
                "No photo, date of birth, marital status or nationality (anti-discrimination "
                "norms); NexScout never adds them.",
                "Academic CVs for PhD programs have no page limit; statements of purpose are "
                "usually 1-2 pages unless the program says otherwise.",
            ),
            countries=frozenset({"united states", "usa", "us", "canada", "ca"}),
        ),
        FormatProfile(
            key="uk_ireland",
            label="UK and Ireland",
            paper="A4",
            date_style="month_year",
            date_first=False,
            page_limits={**_STD_LIMITS, DocType.RESUME: 2},
            contact_hint="town, phone, email, LinkedIn (optional)",
            notes=(
                "A CV is usually two A4 pages; no photo or date of birth.",
                "PhD applications usually ask for a personal statement of 1-2 pages.",
            ),
            countries=frozenset(
                {
                    "united kingdom",
                    "uk",
                    "gb",
                    "great britain",
                    "england",
                    "scotland",
                    "wales",
                    "northern ireland",
                    "ireland",
                    "ie",
                }
            ),
        ),
        FormatProfile(
            key="dach",
            label="German-speaking (Lebenslauf: Germany, Austria, Switzerland)",
            paper="A4",
            date_style="numeric",
            date_first=True,
            page_limits={**_STD_LIMITS, DocType.RESUME: 2},
            contact_hint="address, phone, email",
            notes=(
                "Tabular CV (Lebenslauf): each entry starts with its dates (MM/YYYY), newest "
                "first.",
                "It ends with place, date and your name; fill in the placeholders and sign if "
                "the employer expects it.",
                "A photo and date of birth are optional and common but not required; NexScout "
                "never adds them.",
                "If the posting is in German, a German-language version is often expected.",
            ),
            signature_line=True,
            countries=frozenset(
                {
                    "germany",
                    "de",
                    "deutschland",
                    "austria",
                    "at",
                    "österreich",
                    "switzerland",
                    "ch",
                    "schweiz",
                    "suisse",
                    "liechtenstein",
                }
            ),
        ),
        FormatProfile(
            key="europass",
            label="European (Europass-style)",
            paper="A4",
            date_style="numeric",
            date_first=True,
            page_limits={**_STD_LIMITS, DocType.RESUME: 2},
            contact_hint="city, country, phone, email",
            notes=(
                "Europass-style order: work experience, education and training, then skills; "
                "dates as MM/YYYY.",
                "Accepted across the EU/EEA; some countries also have local formats.",
            ),
            europass_order=True,
            countries=frozenset(
                {
                    "france",
                    "fr",
                    "netherlands",
                    "nl",
                    "belgium",
                    "be",
                    "luxembourg",
                    "lu",
                    "spain",
                    "es",
                    "portugal",
                    "pt",
                    "italy",
                    "it",
                    "greece",
                    "gr",
                    "denmark",
                    "dk",
                    "sweden",
                    "se",
                    "norway",
                    "no",
                    "finland",
                    "fi",
                    "iceland",
                    "is",
                    "poland",
                    "pl",
                    "czechia",
                    "czech republic",
                    "cz",
                    "slovakia",
                    "sk",
                    "hungary",
                    "hu",
                    "slovenia",
                    "si",
                    "croatia",
                    "hr",
                    "romania",
                    "ro",
                    "bulgaria",
                    "bg",
                    "estonia",
                    "ee",
                    "latvia",
                    "lv",
                    "lithuania",
                    "lt",
                    "malta",
                    "mt",
                    "cyprus",
                    "cy",
                }
            ),
        ),
        FormatProfile(
            key="australia_nz",
            label="Australia and New Zealand",
            paper="A4",
            date_style="month_year",
            date_first=False,
            page_limits={**_STD_LIMITS, DocType.RESUME: 3},
            contact_hint="city, phone, email",
            notes=(
                "Resumes are commonly 2-3 pages and end with referees (or 'available on request').",
                "No photo or date of birth.",
            ),
            referees_section=True,
            countries=frozenset({"australia", "au", "new zealand", "nz"}),
        ),
        FormatProfile(
            key="international",
            label="International (globally accepted)",
            paper="A4",
            date_style="month_year",
            date_first=False,
            page_limits={**_STD_LIMITS, DocType.RESUME: 2},
            contact_hint="city and country, phone, email",
            notes=(
                "Reverse-chronological, plain headings, no photo or personal details beyond "
                "contact information: the most widely accepted layout.",
                "Used when the location is unknown or has no specific format in NexScout. "
                "Check the employer's instructions: some countries (e.g. Japan's rirekisho) "
                "use standard forms NexScout can't produce.",
            ),
        ),
    )
}
DEFAULT_KEY = "international"


@dataclass(frozen=True)
class FormatChoice:
    profile: FormatProfile
    reason: str

    def as_dict(self) -> dict[str, object]:
        p = self.profile
        return {
            "key": p.key,
            "label": p.label,
            "paper": p.paper,
            "reason": self.reason,
            "notes": list(p.notes),
            "page_limits": {k.value: v for k, v in p.page_limits.items()},
        }


def _norm(country: str) -> str:
    return re.sub(r"[^a-zäöüéèçß ]", "", country.strip().lower()).strip()


def resolve_format(country: str | None, override: str | None = None) -> FormatChoice:
    """Pick a format: explicit choice > the opportunity's country > international fallback."""
    if override and override in PROFILES:
        return FormatChoice(PROFILES[override], "Chosen by you.")
    if country and country.strip():
        c = _norm(country)
        for p in PROFILES.values():
            if c in p.countries:
                return FormatChoice(p, f"The position is in {country.strip()}.")
        return FormatChoice(
            PROFILES[DEFAULT_KEY],
            f"No specific format for {country.strip()} yet, so the international format is used.",
        )
    return FormatChoice(
        PROFILES[DEFAULT_KEY],
        "The location isn't known, so the globally accepted international format is used.",
    )


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_date(value: str | None, style: DateStyle) -> str:
    """'2021-03' → 'Mar 2021' | '03/2021' | '2021-03'; a bare year stays a year."""
    if not value:
        return ""
    if value == "present":
        return "present"
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-\d{2})?", value)
    if not m:
        return value
    year, month = m.group(1), m.group(2)
    if not month:
        return year
    if style == "month_year":
        return f"{_MONTHS[int(month) - 1]} {year}"
    if style == "numeric":
        return f"{month}/{year}"
    return f"{year}-{month}"
