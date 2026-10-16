import pytest

from nexscout.domain.cases import (
    MAX_CASE_NAME,
    CareerPath,
    normalize_case_name,
    normalize_description,
)
from nexscout.domain.errors import ValidationFailed


def test_case_name_whitespace_is_collapsed() -> None:
    assert normalize_case_name("  My   PhD\tsearch ") == "My PhD search"


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_CASE_NAME + 1)])
def test_invalid_case_names_rejected(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        normalize_case_name(bad)


def test_blank_description_becomes_none() -> None:
    assert normalize_description("   ") is None
    assert normalize_description(None) is None


def test_career_path_flags() -> None:
    assert CareerPath.BOTH.phd_enabled
    assert CareerPath.BOTH.employment_enabled
    assert CareerPath.PHD.phd_enabled
    assert not CareerPath.PHD.employment_enabled
    assert not CareerPath.UNDECIDED.phd_enabled
    assert not CareerPath.UNDECIDED.employment_enabled
