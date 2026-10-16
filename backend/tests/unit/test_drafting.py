"""The drafting verifier: only supported sentences survive; gaps become placeholders."""

from typing import Any

from nexscout.domain.drafting import (
    DocType,
    DraftDocument,
    assemble_academic_cv,
    find_placeholders,
    verify_draft,
)

FACTS: dict[str, dict[str, Any]] = {
    "f-edu": {
        "id": "f-edu",
        "section": "education",
        "label": "MSc at Sampleford",
        "data": {
            "institution": "Sampleford",
            "degree": "MSc",
            "start": "2021",
            "end": "2023",
            "grade": "1.3",
        },
    },
    "f-sk": {"id": "f-sk", "section": "skill", "label": "Python", "data": {"name": "Python"}},
}
FINDINGS = {
    "r-dl": {
        "id": "r-dl",
        "kind": "deadline",
        "summary": "Deadline 1 December 2026",
        "value": {"date": "2026-12-01"},
    }
}
LISTING = "PhD in NLP\nUni\nFully funded 3-year position."


def _s(
    text: str, kind: str, fact_ids: list[str] | None = None, finding_ids: list[str] | None = None
) -> dict[str, Any]:
    return {
        "text": text,
        "kind": kind,
        "fact_ids": fact_ids or [],
        "finding_ids": finding_ids or [],
        "new_paragraph": False,
    }


def _verify(sentences: list[dict[str, Any]], heading: str = "Motivation") -> Any:
    draft = DraftDocument.model_validate(
        {"title": "SOP", "sections": [{"heading": heading, "sentences": sentences}]}
    )
    return verify_draft(draft, DocType.SOP, FACTS, FINDINGS, LISTING)


def test_supported_claims_kept_unsupported_removed() -> None:
    out = _verify(
        [
            _s("I earned an MSc at Sampleford with a grade of 1.3.", "claim", ["f-edu"]),
            _s("I graduated top of my class.", "claim"),
            _s("I know Rust.", "claim", ["f-nope"]),
            _s("I studied there for 3 years.", "claim", ["f-sk"]),
        ]
    )
    assert "grade of 1.3" in out.markdown
    reasons = [r["reason"] for r in out.report["removed"]]
    assert reasons[0].startswith("states something about you without citing")
    assert reasons[1].startswith("cites profile entries that don't exist")
    assert reasons[2] == "numbers not in the cited entries: 3"
    assert out.report["claims"] == [
        {"text": "I earned an MSc at Sampleford with a grade of 1.3.", "fact_ids": ["f-edu"]}
    ]


def test_numbers_are_whole_tokens() -> None:
    # "3" must not be "supported" by "2023" in the cited entry.
    out = _verify([_s("I studied for 3 years.", "claim", ["f-edu"])])
    assert out.report["removed"]
    assert "3" in out.report["removed"][0]["reason"]


def test_position_sentences_checked_against_research_and_listing() -> None:
    out = _verify(
        [
            _s("The deadline is 1 December 2026.", "position", finding_ids=["r-dl"]),
            _s("It is a fully funded 3-year position.", "position"),
            _s("The stipend is 2,500 per month.", "position"),
            _s("See the call.", "position", finding_ids=["r-ghost"]),
        ]
    )
    assert "1 December 2026" in out.markdown
    assert "3-year" in out.markdown
    assert [r["text"] for r in out.report["removed"]] == [
        "The stipend is 2,500 per month.",
        "See the call.",
    ]


def test_intent_flagged_and_numbers_rejected() -> None:
    out = _verify(
        [
            _s("I want to build reliable systems.", "intent"),
            _s("I plan to publish 5 papers.", "intent"),
        ]
    )
    assert out.report["to_check"][0]["text"] == "I want to build reliable systems."
    assert out.report["removed"][0]["reason"].startswith("a statement of intent")


def test_missing_sections_become_placeholders_in_order() -> None:
    out = _verify([_s("[[PLACEHOLDER: why this group]]", "placeholder")])
    headings = [ln[3:] for ln in out.markdown.splitlines() if ln.startswith("## ")]
    assert headings == [
        "Motivation",
        "Academic background",
        "Research experience",
        "Fit with the position",
        "Goals",
    ]
    assert out.report["missing_sections"] == headings[1:]
    assert find_placeholders(out.markdown)[0] == "why this group"
    assert len(out.placeholders) == 5


def test_placeholder_kind_is_always_wrapped() -> None:
    out = _verify([_s("add your motivation", "placeholder")])
    assert "[[PLACEHOLDER: add your motivation]]" in out.markdown


def test_email_has_subject_and_no_headings() -> None:
    draft = DraftDocument.model_validate(
        {
            "title": "Inquiry",
            "sections": [
                {"heading": "Greeting", "sentences": [_s("Dear Dr. Sample,", "position")]}
            ],
        }
    )
    out = verify_draft(draft, DocType.INQUIRY_EMAIL, FACTS, FINDINGS, LISTING)
    assert out.markdown.startswith("Subject: Inquiry\n")
    assert "## " not in out.markdown


def test_academic_cv_lines_map_to_entries() -> None:
    out = assemble_academic_cv("Ada Example", list(FACTS.values()))
    assert out.markdown.startswith("# Ada Example")
    dash = chr(0x2013)
    assert f"**MSc at Sampleford**, Grade: 1.3, 2021 {dash} 2023" in out.markdown
    assert "## Skills\n\nPython" in out.markdown
    assert [c["fact_ids"] for c in out.report["claims"]] == [["f-edu"], ["f-sk"]]
    empty = assemble_academic_cv("Ada", [])
    assert "No confirmed profile entries yet" in empty.markdown
