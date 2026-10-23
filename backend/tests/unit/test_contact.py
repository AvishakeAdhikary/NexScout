"""Contact details: validated, suggested from a CV's header, filled into documents by code."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nexscout.domain.contact import ContactDetails, contact_line, fill_placeholders, read_contact
from nexscout.domain.forms import normalize_question

PERSONAS = Path(__file__).parent.parent / "fixtures" / "personas"
ROHAN = ContactDetails(
    full_name="Rohan Example",
    email="rohan.example@example.com",
    phone="+91 00000 00000",
    city="Pune",
    region="Maharashtra",
    country="India",
)


@pytest.mark.parametrize("name", ["rohan_cv.md", "rohan_cv_pdf.txt"])
def test_a_cv_header_is_read_as_suggestions(name: str) -> None:
    assert read_contact((PERSONAS / name).read_text(encoding="utf-8")) == {
        "full_name": "Rohan Example",
        "email": "rohan.example@example.com",
        "phone": "+91 00000 00000",
        "city": "Pune",
        "country": "India",
    }


def test_a_year_range_is_not_a_phone_number() -> None:
    assert "phone" not in read_contact("Ada Example\nBerlin\nStudied 2018 - 2021 at TU\n")


def test_bad_values_are_refused_and_blanks_mean_not_given() -> None:
    with pytest.raises(ValidationError):
        ContactDetails(email="not an email")
    with pytest.raises(ValidationError):
        ContactDetails(phone="call me maybe")
    assert ContactDetails(city="  ").city is None
    with pytest.raises(ValidationError):
        ContactDetails.model_validate({"favourite_colour": "blue"})


def test_the_contact_line_follows_the_regional_format() -> None:
    links = {"linkedin": "https://www.linkedin.com/in/rohan/"}
    assert contact_line(
        ROHAN, "city and state/province, phone, email, LinkedIn (optional)", links
    ) == ("Pune, Maharashtra · +91 00000 00000 · rohan.example@example.com · linkedin.com/in/rohan")
    assert contact_line(ROHAN, "city, country, phone, email", {}) == (
        "Pune, India · +91 00000 00000 · rohan.example@example.com"
    )
    assert contact_line(ROHAN, "address, phone, email", {}).startswith("Pune, Maharashtra, India")
    # Neither an email nor a phone: no line, the placeholder stays.
    assert contact_line(ContactDetails(city="Pune"), "city, phone, email", {}) is None


def test_known_placeholders_are_filled_and_unknown_ones_stay() -> None:
    md = (
        "# Rohan Example\n\n[[PLACEHOLDER: contact details (city, country, phone, email)]]\n\n"
        "Thank you. [[PLACEHOLDER: your name and contact details]]\n\n"
        "[[PLACEHOLDER: why this role and team, in your own words]]\n\n"
        "[[PLACEHOLDER: earliest start date]]"
    )
    out = fill_placeholders(
        md,
        contact=ROHAN,
        name="Account Name",
        links={},
        answers={normalize_question("earliest start date"): "1 March 2027"},
    )
    assert "Pune, India · +91 00000 00000 · rohan.example@example.com" in out
    assert "Rohan Example  \nPune, India" in out  # the sign-off: name, then the contact line
    assert "1 March 2027" in out
    assert "[[PLACEHOLDER: why this role and team, in your own words]]" in out
    assert out.count("[[PLACEHOLDER:") == 1
    # Without contact details the contact placeholders stay.
    bare = fill_placeholders(md, contact=None, name="X", links={}, answers={})
    assert bare.count("[[PLACEHOLDER:") == 4
