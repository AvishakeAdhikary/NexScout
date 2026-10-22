import pytest

from nexscout.domain.errors import ValidationFailed
from nexscout.domain.profile import (
    SECTION_SCHEMAS,
    Section,
    fact_label,
    find_gaps,
    identity_keys,
    validate_fact_data,
)


def test_every_section_has_a_schema() -> None:
    assert set(SECTION_SCHEMAS) == set(Section)


def test_partial_dates_and_present_are_normalized() -> None:
    data = validate_fact_data(
        Section.EMPLOYMENT,
        {"organization": " Acme ", "title": "Engineer", "start": "2019-09", "end": "Present"},
    )
    assert data == {
        "organization": "Acme",
        "title": "Engineer",
        "start": "2019-09",
        "end": "present",
    }


@pytest.mark.parametrize("bad", ["Sept 2019", "2019-13", "19", "present"])
def test_invalid_start_dates_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_fact_data(Section.EDUCATION, {"institution": "Uni", "start": bad})


def test_unknown_fields_rejected() -> None:
    with pytest.raises(ValidationFailed, match="Extra inputs"):
        validate_fact_data(Section.SKILL, {"name": "Python", "proficiency_score": 99})


def test_required_fields_enforced() -> None:
    with pytest.raises(ValidationFailed, match="title"):
        validate_fact_data(Section.EMPLOYMENT, {"organization": "Acme"})


def test_labels() -> None:
    assert fact_label(Section.EMPLOYMENT, {"title": "Engineer", "organization": "Acme"}) == (
        "Engineer at Acme"
    )
    assert (
        fact_label(
            Section.EDUCATION, {"institution": "Uni", "degree": "BSc", "field_of_study": "Physics"}
        )
        == "BSc, Physics at Uni"
    )
    assert fact_label(Section.SKILL, {"name": "SQL"}) == "SQL"


def test_gaps_for_empty_profile() -> None:
    codes = {g.code for g in find_gaps([])}
    assert codes == {"missing_summary", "missing_education", "missing_skills", "missing_experience"}


def test_gaps_for_entries() -> None:
    facts = [
        ("e1", Section.EDUCATION, {"institution": "Uni"}),
        (
            "j1",
            Section.EMPLOYMENT,
            {"organization": "A", "title": "T", "start": "2022", "end": "2020"},
        ),
        ("s1", Section.SKILL, {"name": "Python"}),
        ("m1", Section.SUMMARY, {"text": "Hi"}),
    ]
    gaps = find_gaps(facts)
    by_code = {(g.code, g.fact_id) for g in gaps}
    assert ("missing_dates", "e1") in by_code
    assert ("missing_degree", "e1") in by_code
    assert ("end_before_start", "j1") in by_code
    assert not any(g.code == "missing_experience" for g in gaps)


def test_present_end_is_not_before_start() -> None:
    facts = [
        (
            "j1",
            Section.EMPLOYMENT,
            {"organization": "A", "title": "T", "start": "2022", "end": "present"},
        )
    ]
    assert not any(g.code == "end_before_start" for g in find_gaps(facts))


def test_the_same_job_is_recognised_after_the_user_edits_it() -> None:
    from_cv = {
        "organization": "Example Analytics",
        "title": "Machine Learning Engineer | Graduate Engineer",
        "start": "2023-08",
    }
    edited = {
        "organization": "Example Analytics Private Limited",
        "title": "Machine Learning Engineer (Graduate Engineer)",
        "start": "2023-08",
    }
    assert identity_keys(Section.EMPLOYMENT, from_cv) & identity_keys(Section.EMPLOYMENT, edited)
    other = {**from_cv, "start": "2019-01"}
    assert not identity_keys(Section.EMPLOYMENT, other) & identity_keys(Section.EMPLOYMENT, edited)
