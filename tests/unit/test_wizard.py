"""Tests for the interactive ``nexscout init`` wizard."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from nexscout import wizard
from nexscout.core.profile import Profile


def _answers(extra: dict[str, str] | None = None) -> Iterator[str]:
    """Default sequence the wizard expects via ``Prompt.ask`` / ``IntPrompt.ask`` / ``Confirm.ask``."""
    seq = [
        "Jane Q. Public",  # legal
        "Jane",  # pref
        "jane@example.com",  # email
        "+1-415-555-0100",  # phone
        "San Francisco",  # city
        "CA",  # region
        "USA",  # country
        "94110",  # postcode
        "linkedin.com/in/jane",  # li
        "github.com/jane",  # gh
        "https://jane.dev",  # web
        "y",  # authorized
        "n",  # sponsor
        "USC",  # permit
        "165000",  # expect
        "148500",  # pay_min
        "198000",  # pay_max
        "USD",  # currency
        "7",  # years
        "BSc Computer Science",
        "Senior Software Engineer",
        "Staff Engineer, Senior Backend Engineer",
        "Python, Go",  # languages
        "FastAPI, React",  # frameworks
        "Docker, AWS",  # infra
        "Postgres, Redis",  # data
        "Git, Linux",  # tools
        "Acme, Globex",
        "Search Indexer",
        "State University",
        "p99 -40%",
        "capsolver",
    ]
    if extra:
        seq = list(extra.values())
    yield from seq


def test_run_wizard_writes_valid_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The full Q&A flow produces a YAML that ``Profile.from_path`` accepts."""
    answers = _answers()
    out = tmp_path / "profile.yaml"
    monkeypatch.setattr("rich.prompt.Prompt.ask", staticmethod(lambda *a, **kw: next(answers)))
    monkeypatch.setattr("rich.prompt.IntPrompt.ask", staticmethod(lambda *a, **kw: int(next(answers))))
    monkeypatch.setattr(
        "rich.prompt.Confirm.ask",
        staticmethod(lambda *a, **kw: next(answers).lower().startswith("y")),
    )

    written = wizard.run_wizard(out_path=out, force=True)
    assert written == out
    assert out.exists()

    loaded = Profile.from_path(out)
    assert loaded.me.legal == "Jane Q. Public"
    assert loaded.me.email == "jane@example.com"
    assert loaded.pay.expect == 165000
    assert "Python" in loaded.skills.lang
    assert loaded.captcha.provider == "capsolver"


def test_run_wizard_aborts_on_existing_no(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If target exists and user answers 'no' to overwrite, the file is left untouched."""
    out = tmp_path / "profile.yaml"
    out.write_text("legacy: true\n")
    monkeypatch.setattr("rich.prompt.Confirm.ask", staticmethod(lambda *a, **kw: False))
    result = wizard.run_wizard(out_path=out, force=False)
    assert result == out
    # File still has original content (not overwritten).
    assert out.read_text() == "legacy: true\n"


def test_split_csv() -> None:
    assert wizard._split_csv("a, b ,  c") == ["a", "b", "c"]
    assert wizard._split_csv("") == []
    assert wizard._split_csv("only") == ["only"]
