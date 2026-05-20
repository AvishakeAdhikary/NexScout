"""sanitize_text — em/en dashes and smart quotes rewritten to ASCII."""

from __future__ import annotations

from nexscout.scoring.validator import sanitize_text


def test_em_dash_with_spaces_becomes_comma() -> None:
    assert sanitize_text("Built a thing — fast and reliable") == "Built a thing, fast and reliable"


def test_bare_em_dash_becomes_comma() -> None:
    assert sanitize_text("Built—fast") == "Built, fast"


def test_en_dash_becomes_hyphen() -> None:
    assert sanitize_text("2020–2025") == "2020-2025"


def test_smart_quotes_normalised() -> None:
    assert sanitize_text("“hello” ‘world’") == '"hello" \'world\''


def test_whitespace_is_stripped() -> None:
    assert sanitize_text("  hello  \n") == "hello"
