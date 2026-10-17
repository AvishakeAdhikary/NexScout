"""Regional document formats: resolution, date styles, layouts, and posting-limit parsing."""

from typing import Any

import pytest

from nexscout.domain.compliance import check_document, posting_requirements, word_count
from nexscout.domain.drafting import DocType, assemble_academic_cv, assemble_resume
from nexscout.domain.formats import PROFILES, format_date, resolve_format

FACTS: list[dict[str, Any]] = [
    {
        "id": "e",
        "section": "employment",
        "label": "ML Engineer at Examplecorp",
        "data": {
            "title": "ML Engineer",
            "organization": "Examplecorp",
            "start": "2021-03",
            "end": "present",
        },
    },
    {
        "id": "d",
        "section": "education",
        "label": "MSc at Sampleford",
        "data": {"institution": "Sampleford", "degree": "MSc", "start": "2019", "end": "2021-06"},
    },
    {"id": "s", "section": "skill", "label": "Python", "data": {"name": "Python"}},
]


@pytest.mark.parametrize(
    ("country", "key"),
    [
        ("Germany", "dach"),
        ("Österreich", "dach"),
        ("CH", "dach"),
        ("United States", "north_america"),
        ("canada", "north_america"),
        ("United Kingdom", "uk_ireland"),
        ("Ireland", "uk_ireland"),
        ("Netherlands", "europass"),
        ("France", "europass"),
        ("Australia", "australia_nz"),
        ("Japan", "international"),
        ("", "international"),
        (None, "international"),
    ],
)
def test_resolution(country: str | None, key: str) -> None:
    choice = resolve_format(country)
    assert choice.profile.key == key
    assert choice.reason


def test_override_wins_and_fallback_reason_is_honest() -> None:
    assert resolve_format("Germany", "north_america").profile.key == "north_america"
    assert resolve_format("Germany", "bogus").profile.key == "dach"
    assert "No specific format for Japan" in resolve_format("Japan").reason
    assert "isn't known" in resolve_format(None).reason
    assert PROFILES["north_america"].paper == "Letter"
    assert all(p.paper == "A4" for k, p in PROFILES.items() if k != "north_america")


def test_dates() -> None:
    assert format_date("2021-03", "month_year") == "Mar 2021"
    assert format_date("2021-03", "numeric") == "03/2021"
    assert format_date("2021", "numeric") == "2021"
    assert format_date("present", "numeric") == "present"
    assert format_date(None, "numeric") == ""


def test_dach_lebenslauf_is_date_first_and_ends_with_place_date() -> None:
    md = assemble_resume("Ada Example", FACTS, PROFILES["dach"]).markdown
    assert "- 03/2021 \u2013 present \u00b7 **ML Engineer at Examplecorp**" in md
    assert md.rstrip().endswith("[[PLACEHOLDER: place]], [[PLACEHOLDER: date]]\n\nAda Example")
    assert "photo" not in md.lower()
    assert "birth" not in md.lower()


def test_europass_order_and_us_dates() -> None:
    eu = assemble_resume("Ada", FACTS, PROFILES["europass"]).markdown
    assert (
        eu.index("## Work experience")
        < eu.index("## Education and training")
        < eu.index("## Skills")
    )
    us = assemble_resume("Ada", FACTS, PROFILES["north_america"]).markdown
    assert "**ML Engineer at Examplecorp**, Mar 2021 \u2013 present" in us
    assert "LinkedIn (optional)" in us  # contact hint follows the region


def test_referees_only_from_shareable_entries() -> None:
    au = assemble_academic_cv("Ada", FACTS, PROFILES["australia_nz"]).markdown
    assert "## Referees" in au
    assert "[[PLACEHOLDER: referees" in au  # nothing invented when none are shareable
    ref = {
        "id": "r",
        "section": "reference",
        "label": "Dr. Sample",
        "data": {"name": "Dr. Sample", "relationship": "Supervisor"},
    }
    au2 = assemble_academic_cv("Ada", [*FACTS, ref], PROFILES["australia_nz"])
    assert "- Dr. Sample, Supervisor" in au2.markdown
    assert ["r"] in [c["fact_ids"] for c in au2.report["claims"]]


def test_posting_limits_are_found_per_document() -> None:
    findings = [
        {
            "kind": "document_required",
            "field": "statement",
            "quote": "Research statement (max. 2 pages) describing your interest",
        },
        {
            "kind": "document_required",
            "field": "statement",
            "quote": "A cover letter of no more than 400 words",
        },
        {"kind": "document_required", "field": "cv", "quote": "CV (maximum 3 pages)"},
        {"kind": "deadline", "field": "application", "quote": "max. 2 pages"},
    ]
    assert [r["pages"] for r in posting_requirements(DocType.SOP, findings)] == [2]
    assert [r["words"] for r in posting_requirements(DocType.COVER_LETTER, findings)] == [400]
    assert [r["pages"] for r in posting_requirements(DocType.RESUME, findings)] == [3]
    assert posting_requirements(DocType.INQUIRY_EMAIL, findings) == []


def test_compliance_severity() -> None:
    fmt = resolve_format("United Kingdom").as_dict()
    findings = [
        {
            "kind": "document_required",
            "field": "statement",
            "quote": "Personal statement (max. 2 pages)",
        }
    ]
    ok = check_document(DocType.SOP, "# SOP\n\nShort.", 1, fmt, findings)
    assert ok["status"] == "ok"
    long_ = check_document(DocType.SOP, "# SOP\n\nLong.", 3, fmt, findings)
    assert long_["status"] == "blocking"
    warn = check_document(DocType.RESUME, "# CV\n\nx", 3, fmt, [])
    assert warn["status"] == "warnings"  # convention only: 2 pages in the UK
    assert word_count("Hello [[PLACEHOLDER: x y z]] world") == 2
