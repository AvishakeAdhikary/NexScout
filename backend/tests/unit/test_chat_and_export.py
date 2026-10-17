"""Assistant intent routing (fixed menu) and CSV export safety."""

import pytest

from nexscout.application.applications import _csv_cell
from nexscout.domain.chat import classify


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("What needs me?", "needs_you"),
        ("anything waiting on me", "needs_you"),
        ("upcoming deadlines please", "deadlines"),
        ("Find PhD positions in NLP", "find_phd"),
        ("search for jobs in Berlin", "find_jobs"),
        ("Create my academic CV", "draft_academic_cv"),
        ("make my resume", "draft_resume"),
        ("review my profile", "review_profile"),
        ("submit my application now", "submit"),
        ("please send it for me", "submit"),
        ("hello", "help"),
        ("what's the weather like", "unknown"),
    ],
)
def test_intents(message: str, intent: str) -> None:
    assert classify(message).name == intent


def test_status_query_keeps_only_the_subject() -> None:
    it = classify("What is the status of my application to Acme GmbH?")
    assert it.name == "status"
    assert it.args["q"] == "acme gmbh"


@pytest.mark.parametrize("value", ['=HYPERLINK("x")', "+1", "-2", "@SUM(A1)", "\tx"])
def test_csv_formula_injection_neutralized(value: str) -> None:
    assert _csv_cell(value).startswith("'")


def test_csv_plain_values_unchanged() -> None:
    assert _csv_cell("Acme GmbH") == "Acme GmbH"
    assert _csv_cell(None) == ""
