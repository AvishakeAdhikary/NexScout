"""FABRICATION_WATCHLIST scan — skills block flagged regardless of mode."""

from __future__ import annotations

from nexscout.core.profile import Profile
from nexscout.scoring.validator import has_fabrication, validate_json_fields


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "X", "pref": "X", "email": "x@x", "phone": "1"},
            "facts": {"companies": ["Acme"], "school": "State U"},
            "skills": {"lang": ["Python"]},
        }
    )


def test_has_fabrication_finds_watchlisted_term() -> None:
    assert has_fabrication("AWS certified developer") in {"aws certified", "certified"}
    assert has_fabrication("Knows Rust well") == "rust"
    assert has_fabrication("Python and FastAPI") is None


def test_skills_block_with_rust_is_rejected() -> None:
    profile = _profile()
    data = {
        "title": "Senior Engineer",
        "summary": "Built things.",
        "skills": {"Languages": "Python, Rust"},  # Rust is on the watchlist
        "experience": [{"header": "Eng at Acme", "subtitle": "x", "bullets": ["b"]}],
        "projects": [{"header": "x", "subtitle": "y", "bullets": ["b"]}],
        "education": "State U | BSc",
    }
    result = validate_json_fields(data, profile, "normal")
    assert any("fabrication" in e and "rust" in e for e in result.errors)


def test_missing_company_in_experience_is_rejected() -> None:
    profile = _profile()
    data = {
        "title": "Senior Engineer",
        "summary": "Built things.",
        "skills": {"Languages": "Python"},
        "experience": [{"header": "Eng at Globex", "subtitle": "x", "bullets": ["b"]}],
        "projects": [{"header": "x", "subtitle": "y", "bullets": ["b"]}],
        "education": "State U | BSc",
    }
    result = validate_json_fields(data, profile, "normal")
    assert any("preserved company" in e for e in result.errors)
