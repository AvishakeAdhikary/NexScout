"""Recommendation letters become one reference entry: who recommends you, never claims."""

from pathlib import Path

from nexscout.domain.letters import read_reference

FIXTURES = Path(__file__).parent.parent / "fixtures" / "personas"


def test_informal_letter_without_a_closing_phrase() -> None:
    text = (FIXTURES / "letter_informal.txt").read_text(encoding="utf-8")
    ref = read_reference(text)
    assert ref is not None
    assert ref.data == {
        "name": "Asha Sample",
        "relationship": 'Professor and Principal — "as my student"',
        "organization": "Example Institute of Management and Technology",
        "contact": "asha.sample@example-institute.edu",  # the signature's, not the letterhead's
    }
    assert ref.relationship_quote is not None
    assert "since 2018 as my student" in ref.relationship_quote
    assert "StationRoad" not in ref.relationship_quote  # the letterhead isn't the letter
    assert ref.excerpt == text[ref.start : ref.end]
    assert "Rohan Example" not in str(ref.data)  # nothing about the candidate


def test_formal_letter_after_sincerely() -> None:
    ref = read_reference((FIXTURES / "letter_formal.txt").read_text(encoding="utf-8"))
    assert ref is not None
    assert ref.data["name"] == "Dr. Vikram Sample"
    assert ref.data["organization"] == "Example University Pune"  # the university, not a school
    assert ref.data["relationship"] == (
        'Assistant Professor (Grade III) — "As his professor and academic advisor"'
    )
    assert ref.data["contact"] == "00000 00000"  # the signature's phone beats the letterhead


def test_no_signature_no_reference() -> None:
    assert read_reference("") is None
    assert read_reference("just one sentence of praise.") is None
