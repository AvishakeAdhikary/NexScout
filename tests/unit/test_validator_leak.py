"""LLM leak-phrase detector — substring matcher, always errors in every mode."""

from __future__ import annotations

from nexscout.core.profile import Profile
from nexscout.scoring.validator import has_leak_phrase, validate_cover_letter, validate_json_fields


def _profile() -> Profile:
    return Profile.model_validate({
        "me": {"legal": "X", "pref": "X", "email": "x@x", "phone": "1"},
        "facts": {"companies": ["Acme"], "school": "State U"},
        "skills": {"lang": ["Python"]},
    })


def test_leak_phrase_detected_anywhere() -> None:
    assert has_leak_phrase("I am sorry for the confusion") == "i am sorry"
    assert has_leak_phrase("Here is the revised resume") == "here is the revised"


def test_leak_in_cover_letter_is_always_error() -> None:
    profile = _profile()
    text = "Dear Hiring Manager, here is the revised letter. Built X. Thanks."
    for mode in ("strict", "normal", "lenient"):
        result = validate_cover_letter(text, profile, mode)  # type: ignore[arg-type]
        assert not result.ok
        assert any("leak phrase" in e for e in result.errors)


def test_leak_in_tailor_json_is_always_error() -> None:
    profile = _profile()
    data = {
        "title": "Senior Engineer",
        "summary": "Here is the revised summary",
        "skills": {"Languages": "Python"},
        "experience": [{"header": "Eng at Acme", "subtitle": "x", "bullets": ["b"]}],
        "projects": [{"header": "x", "subtitle": "y", "bullets": ["b"]}],
        "education": "State U | BSc",
    }
    result = validate_json_fields(data, profile, "lenient")
    assert any("leak phrase" in e for e in result.errors)
