from nexscout.domain.cv_heuristics import (
    extract_facts,
    find_range,
    heading_section,
    split_sections,
    to_partial_date,
)
from nexscout.domain.profile import Section
from tests.fixtures.documents import ada_cv_text


def test_heading_detection() -> None:
    assert heading_section("## Work Experience") is Section.EMPLOYMENT
    assert heading_section("EDUCATION:") is Section.EDUCATION
    assert heading_section("**Honors & Awards**") is Section.AWARD
    assert heading_section("I have experience in many things here") is None


def test_dates() -> None:
    assert to_partial_date("Sep 2019") == "2019-09"
    assert to_partial_date("September 2019") == "2019-09"
    assert to_partial_date("Sept. 2019") == "2019-09"
    assert to_partial_date("03/2020") == "2020-03"
    assert to_partial_date("2018") == "2018"
    assert to_partial_date("Present") == "present"
    assert find_range("Engineer | Jan 2021 - Present")[:2] == ("2021-01", "present")
    assert find_range("2015 – 2018")[:2] == ("2015", "2018")
    assert find_range("no dates here") == (None, None, None)


def test_sections_skip_contact_header() -> None:
    blocks = split_sections(ada_cv_text())
    assert [b.section for b in blocks][:3] == [
        Section.SUMMARY,
        Section.EDUCATION,
        Section.EMPLOYMENT,
    ]
    # The name/email header before the first heading is never turned into facts.
    facts = extract_facts(ada_cv_text())
    assert not any("ada.example@example.com" in str(f.data) for f in facts)


def _by(section: Section, facts: list) -> list[dict]:  # type: ignore[type-arg]
    return [f.data for f in facts if f.section is section]


def test_extracts_fixture_cv_conservatively() -> None:
    text = ada_cv_text()
    facts = extract_facts(text)

    jobs = _by(Section.EMPLOYMENT, facts)
    assert {
        "title": "Machine Learning Engineer",
        "organization": "Examplecorp GmbH",
        "start": "2021-01",
        "end": "present",
    }.items() <= jobs[0].items()
    assert jobs[1]["title"] == "Data Analyst"
    assert jobs[1]["organization"] == "Sample Analytics Ltd"
    assert "Mentored two junior engineers" in jobs[0]["description"]

    edu = _by(Section.EDUCATION, facts)
    assert edu[0]["institution"] == "Technical University of Exampleton"
    assert edu[0]["degree"] == "MSc"
    assert edu[0]["field_of_study"] == "Computer Science"
    assert (edu[0]["start"], edu[0]["end"]) == ("2018-10", "2020-09")
    assert edu[1]["institution"] == "University of Sampleford"

    skills = {d["name"] for d in _by(Section.SKILL, facts)}
    assert {"Python", "SQL", "TypeScript", "PyTorch", "scikit-learn", "Git", "Docker"} <= skills
    assert not any(":" in s for s in skills)

    pubs = _by(Section.PUBLICATION, facts)
    assert pubs[0]["year"] == "2022"
    assert pubs[0]["doi"] == "10.1234/example.5678"

    assert _by(Section.CERTIFICATION, facts)[0] == {
        "name": "AWS Certified Cloud Practitioner",
        "date": "2021",
    }
    assert _by(Section.VOLUNTEER, facts)[0]["organization"] == "Code Club Exampleton"
    assert _by(Section.REFERENCE, facts) == []  # "Available on request" is not a reference
    assert _by(Section.SUMMARY, facts)[0]["text"].startswith("Machine learning engineer")


def test_every_fact_has_verbatim_evidence_span() -> None:
    text = ada_cv_text()
    for fact in extract_facts(text):
        assert 0 <= fact.start < fact.end <= len(text)
        assert fact.excerpt == text[fact.start : fact.end][:1000]
        assert fact.excerpt.strip()


def test_unparseable_entry_falls_back_to_other_with_warning() -> None:
    text = "Experience\nDid lots of things for many years\n"
    facts = extract_facts(text)
    assert len(facts) == 1
    assert facts[0].section is Section.OTHER
    assert facts[0].confidence == "low"
    assert facts[0].warnings
    assert facts[0].data["title"] == "Did lots of things for many years"


def test_no_headings_means_no_facts() -> None:
    assert extract_facts("Just a paragraph of prose with no structure.") == []
