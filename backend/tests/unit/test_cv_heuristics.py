from pathlib import Path

import pytest

from nexscout.domain.cv_heuristics import (
    extract_facts,
    find_range,
    heading_section,
    split_sections,
    to_partial_date,
)
from nexscout.domain.profile import Section, fact_label
from tests.fixtures.documents import ada_cv_text

FIXTURES = Path(__file__).parent.parent / "fixtures" / "personas"


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


# ------------------------------------------------------------------ v2 (M18, from a real CV)
def _labels(facts: list) -> list[tuple[str, str]]:  # type: ignore[type-arg]
    return [(f.section.value, fact_label(f.section, f.data)) for f in facts]


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_markdown_and_its_pdf_text_read_the_same() -> None:
    md = extract_facts(_read("rohan_cv.md"))
    pdf = extract_facts(_read("rohan_cv_pdf.txt"))
    assert _labels(md) == _labels(pdf)
    jobs = _by(Section.EMPLOYMENT, md)
    assert [(j["title"], j["organization"], j["location"]) for j in jobs] == [
        ("Machine Learning Engineer", "Lumen Robotics", "Pune, India"),
        ("Teaching Assistant", "Example Institute of Technology", "Pune, India"),
    ]
    assert "VisionDesk" in jobs[0]["description"]
    edu = _by(Section.EDUCATION, pdf)[0]
    assert edu["degree"] == "Master of Computer Applications (MCA)"
    assert edu["location"] == "Pune, India"  # the wrapped school name isn't the place


def test_no_markdown_or_split_brackets_in_any_field() -> None:
    for name in ("rohan_cv.md", "rohan_cv_pdf.txt"):
        facts = extract_facts(_read(name))
        assert not any(f.section is Section.OTHER for f in facts), name
        for f in facts:
            for value in f.data.values():
                text = str(value)
                assert "**" not in text, (name, text)
                assert "`" not in text, (name, text)
                assert "](" not in text, (name, text)
            label = fact_label(f.section, f.data)
            assert label.count("(") == label.count(")"), label


def test_skill_lists_split_only_at_the_top_level() -> None:
    facts = extract_facts(_read("rohan_cv_pdf.txt"))
    skills = {d["name"]: d.get("category") for d in _by(Section.SKILL, facts)}
    assert {"JavaScript", "React.js", "Angular", "llama.cpp", "GGUF", "Express.js"} <= set(skills)
    assert "Retrieval-Augmented Generation (RAG)" in skills  # an acronym stays with its name
    assert "LoRA/QLoRA Fine-Tuning" in skills  # not split: it has spaces
    assert "CI/CD Pipelines" in skills
    assert skills["Python"] == "Programming"
    assert skills["German"] == "Spoken languages"
    assert {d["name"]: d.get("level") for d in _by(Section.SKILL, facts)}["Hindi"] == "Native"


@pytest.mark.parametrize("name", ["rohan_cv.md", "rohan_cv_pdf.txt"])
def test_projects_are_clean_and_linked_to_their_job(name: str) -> None:
    facts = extract_facts(_read(name))
    projects = [f for f in facts if f.section is Section.PROJECT]
    # EdgeCam: the PDF text has a blank line between the name and its date line.
    assert [p.data["name"] for p in projects] == [
        "VisionDesk",
        "Sign Language Reader (LSTM Model)",
        "EdgeCam",
        "Campus Bus Tracker",
    ]
    desk = projects[0]
    assert desk.data["description"].startswith("Autonomous Inspection Kiosk")
    assert desk.data["technologies"] == ["Python", "PyTorch", "ONNX", "Docker"]
    assert [facts[i].data["organization"] for i in desk.related] == ["Lumen Robotics"]
    assert projects[1].data["url"] == "https://github.com/rohan-example/sign-reader"
    assert _by(Section.CERTIFICATION, facts)[0] == {
        "name": "AWS Computer Vision: Getting Started with GluonCV",
        "issuer": "Amazon Web Services",
    }


def test_v2_evidence_is_still_verbatim() -> None:
    for name in ("rohan_cv.md", "rohan_cv_pdf.txt"):
        text = _read(name)
        for fact in extract_facts(text):
            assert fact.excerpt == text[fact.start : fact.end][:1000]
            assert fact.excerpt.strip()


@pytest.mark.parametrize("name", ["rohan_cv.md", "rohan_cv_pdf.txt"])
def test_citations_split_into_authors_title_and_venue(name: str) -> None:
    pubs = _by(Section.PUBLICATION, extract_facts(_read(name)))
    assert pubs[0]["title"] == "Vision Models for Factory Inspection: A Survey"
    assert pubs[0]["authors"] == "R. Example, S. Sample"
    assert pubs[0]["venue"] == "Edge Intelligence"
    assert (pubs[0]["year"], pubs[0]["doi"]) == ("2025", "10.1234/example.2025.1")
    assert pubs[1]["venue"] == "Proc. Example Conference on Vision"  # "Proc." isn't the end


def test_a_link_and_a_title_wrapped_by_the_pdf_are_joined() -> None:
    facts = extract_facts(_read("rohan_cv_pdf.txt"))
    cam = next(f for f in facts if f.data.get("name") == "EdgeCam")
    assert cam.data["url"] == "https://rohan-example.github.io/EdgeCam"
    assert not cam.data["description"].startswith("EdgeCam")


@pytest.mark.parametrize("name", ["rohan_cv.md", "rohan_cv_pdf.txt"])
def test_a_project_at_university_links_to_that_degree(name: str) -> None:
    facts = extract_facts(_read(name))
    bus = next(f for f in facts if f.data.get("name") == "Campus Bus Tracker")
    assert bus.data["url"] == "https://github.com/rohan-example/bus"
    assert [facts[i].data["institution"] for i in bus.related] == ["Example University Pune"]
