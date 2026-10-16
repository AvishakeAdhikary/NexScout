from datetime import date

import pytest

from nexscout.domain.opportunities import (
    NormalizedOpportunity,
    candidate_from,
    canonicalize_url,
    decide,
    normalize_title,
)

DESC = (
    "We are looking for a machine learning engineer to build evaluation pipelines for "
    "language models, work with data scientists, and ship reliable services in Python."
)


def opp(**kw: object) -> NormalizedOpportunity:
    base: dict[str, object] = {
        "source_key": "board_a",
        "external_id": "1",
        "source_url": "https://a.example/jobs/1",
        "kind": "job",
        "title": "Machine Learning Engineer",
        "organization_name": "Acme GmbH",
        "location_city": "Berlin",
        "location_country": "Germany",
        "description": DESC,
        "posted_at": date(2026, 9, 1),
    }
    base.update(kw)
    return NormalizedOpportunity.model_validate(base)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://www.Example.com/jobs/1/?utm_source=x&b=2&a=1#apply",
            "https://example.com/jobs/1?a=1&b=2",
        ),
        ("http://example.com//jobs//1", "https://example.com/jobs/1"),
        ("https://example.com/?gclid=abc", "https://example.com/"),
        ("javascript:alert(1)", None),
        (None, None),
    ],
)
def test_canonicalize_url(raw: str | None, expected: str | None) -> None:
    assert canonicalize_url(raw) == expected


def test_title_normalization_expands_abbreviations() -> None:
    assert normalize_title("Sr. ML Eng (m/f/d)") == "senior machine learning engineer"
    assert normalize_title("Data Scientist II") == "data scientist 2"


def test_same_listing_on_two_boards_is_merged() -> None:
    a = candidate_from(opp())
    b = candidate_from(
        opp(
            source_key="board_b",
            external_id="xyz",
            source_url="https://b.example/p/xyz",
            title="ML Engineer",
            organization_name="ACME",
            posted_at=date(2026, 9, 3),
        )
    )
    d = decide(a, b)
    assert d.duplicate, d.reasons
    assert d.reasons


def test_tracking_params_do_not_create_duplicates() -> None:
    a = candidate_from(opp(canonical_url="https://acme.example/careers/123"))
    b = candidate_from(
        opp(
            source_key="board_b",
            external_id="9",
            canonical_url="https://www.acme.example/careers/123/?utm_campaign=x",
            description="totally different text",
        )
    )
    assert decide(a, b).duplicate


def test_distinct_requisitions_at_same_employer_are_never_merged() -> None:
    a = candidate_from(opp(requisition_id="REQ-100"))
    b = candidate_from(
        opp(
            source_key="board_b",
            external_id="2",
            requisition_id="REQ-200",
            source_url="https://b.example/2",
        )
    )
    d = decide(a, b)
    assert not d.duplicate
    assert "requisition" in d.reasons[0]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"organization_name": "Other Corp"}, "employer"),
        ({"location_city": "Munich"}, "location"),
        ({"kind": "phd"}, "types"),
        ({"posted_at": date(2026, 1, 1)}, "far apart"),
    ],
)
def test_guards_keep_similar_titles_apart(change: dict[str, object], reason: str) -> None:
    a = candidate_from(opp())
    b = candidate_from(
        opp(source_key="board_b", external_id="2", source_url="https://b.example/2", **change)
    )
    d = decide(a, b)
    assert not d.duplicate
    assert any(reason in r for r in d.reasons)


def test_similar_title_but_different_description_is_not_merged() -> None:
    a = candidate_from(opp())
    b = candidate_from(
        opp(
            source_key="board_b",
            external_id="2",
            source_url="https://b.example/2",
            description="Join our infrastructure team to run Kubernetes clusters "
            "and on-call rotations for payment systems.",
        )
    )
    assert not decide(a, b).duplicate
