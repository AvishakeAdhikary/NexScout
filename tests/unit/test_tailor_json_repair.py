"""Tests for the tolerant JSON-repair fallback in the tailor stage.

Weak local models (small reasoning models on LM Studio) sometimes emit
structurally malformed JSON — a missing comma between members, a trailing
comma, or an unquoted key. ``_repair_json_object`` recovers the object when
the strict :func:`extract_json` path fails, but ONLY returns ``dict`` results
so the existing ``isinstance(..., dict)`` guard (and its "bad JSON →
failed_validation" behavior) is preserved for genuinely non-object input.
"""

from __future__ import annotations

from nexscout.scoring.tailor import _repair_json_object


def test_repairs_missing_comma() -> None:
    out = _repair_json_object('{"a": 1 "b": 2}')
    assert out == {"a": 1, "b": 2}


def test_repairs_trailing_comma() -> None:
    out = _repair_json_object('{"a": 1, "b": 2,}')
    assert out == {"a": 1, "b": 2}


def test_repairs_unquoted_key() -> None:
    out = _repair_json_object("{title: 'Engineer', years: 2}")
    assert isinstance(out, dict)
    assert out.get("title") == "Engineer"


def test_empty_returns_none() -> None:
    assert _repair_json_object("") is None


def test_non_object_input_returns_none() -> None:
    # A bare array is valid JSON but not a resume object → rejected so the
    # tailor keeps treating it as "no valid JSON".
    assert _repair_json_object("[1, 2, 3]") is None


def test_pure_garbage_returns_none() -> None:
    # Mirrors test_tailor_resume_bad_json_retries' input: must NOT become a
    # dict, or that test (and the retry contract) would silently change.
    assert _repair_json_object("not json") is None
    assert _repair_json_object("still not json") is None
