"""Run and step failures shown to users never contain Python internals."""

import re

from nexscout.agent_runtime.errors import user_message
from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.fetch import FetchFailed

INTERNALS = re.compile(r"Error\b|Exception\b|Traceback|object has no attribute|NoneType")


def test_intentional_messages_pass_through() -> None:
    assert user_message(ValidationFailed("Choose a CV first.")) == "Choose a CV first."
    assert user_message(FetchFailed("The site took too long to respond.")) == (
        "The site took too long to respond."
    )
    assert user_message(LookupError("The document was deleted.")) == "The document was deleted."


def test_bugs_become_a_plain_sentence_with_a_reference() -> None:
    for exc in (
        AttributeError("'NoneType' object has no attribute 'get'"),
        KeyError("severity"),
        IndexError("list index out of range"),
        TypeError("unsupported operand"),
        ZeroDivisionError("division by zero"),
    ):
        text = user_message(exc)
        assert not INTERNALS.search(text), text
        assert re.search(r"reference [0-9a-f]{8}", text)
