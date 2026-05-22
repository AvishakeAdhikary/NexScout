"""Banned-word detector — \\b boundaries, mode-dependent severity."""

from __future__ import annotations

from nexscout.core.profile import Profile
from nexscout.scoring.validator import has_banned_word, validate_cover_letter


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "X", "pref": "X", "email": "x@x", "phone": "1"},
            "facts": {"companies": ["X"], "school": "U"},
            "skills": {"lang": ["Python"]},
        }
    )


def test_word_boundary_hits_passionate() -> None:
    assert has_banned_word("I am passionate about engineering") == "passionate"


def test_substring_inside_other_word_is_not_a_hit() -> None:
    # "synergy" appears in "synergyzing" — but \b prevents the false positive.
    assert has_banned_word("That synergyz") is None


def test_strict_mode_errors_normal_mode_warns_lenient_ignores() -> None:
    profile = _profile()
    text = "Dear Hiring Manager, I am passionate about the work. Built X. Thanks."

    strict = validate_cover_letter(text, profile, "strict")
    normal = validate_cover_letter(text, profile, "normal")
    lenient = validate_cover_letter(text, profile, "lenient")

    assert any("passionate" in m for m in strict.errors)
    assert not any("passionate" in m for m in normal.errors)
    assert any("passionate" in w for w in normal.warnings)
    assert all("passionate" not in m for m in lenient.errors + lenient.warnings)
