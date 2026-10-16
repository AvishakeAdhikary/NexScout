import pytest

from nexscout.application.auth import normalize_email
from nexscout.domain.errors import ValidationFailed


def test_email_is_normalized_and_lowercased() -> None:
    assert normalize_email("  Ada@Example.COM ") == "ada@example.com"


@pytest.mark.parametrize(
    "bad",
    ["not-an-email", "a@", "@example.com", "a@localhost", "a@example.test", "a@host.invalid"],
)
def test_invalid_or_special_use_emails_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_email(bad)
