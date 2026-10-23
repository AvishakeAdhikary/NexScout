"""The candidate's contact details: entered (or confirmed) once per case, reused everywhere.

They fill the contact line of a resume or CV, the sign-off of a letter, and the name, email,
phone and location fields of an application form. They are never sent to an AI model: the
documents get them after drafting, from plain code (`fill_placeholders`).

`read_contact` only *suggests* details found in a CV's header. Nothing is saved until the user
confirms it.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexscout.domain.drafting import PLACEHOLDER
from nexscout.domain.forms import normalize_question

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE_CHARS = re.compile(r"\+?[\d\s().-]{6,40}")
_PHONE = re.compile(r"\+?\(?\d[\d\s().-]{6,}\d")
_LABEL = re.compile(
    r"\b(Location|Address|Based in|E-?mail|Phone|Mobile|Tel|GitHub|LinkedIn|Website|Portfolio)"
    r"\s*:\s*",
    re.IGNORECASE,
)

Short = Annotated[str | None, Field(default=None, max_length=120)]


class ContactDetails(BaseModel):
    """What forms and documents may use. Every field is optional; empty means "not given"."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    full_name: Annotated[str | None, Field(default=None, max_length=200)] = None
    given_name: Short = None
    family_name: Short = None
    email: Annotated[str | None, Field(default=None, max_length=254)] = None
    phone: Annotated[str | None, Field(default=None, max_length=40)] = None
    address: Annotated[str | None, Field(default=None, max_length=300)] = None
    postal_code: Annotated[str | None, Field(default=None, max_length=20)] = None
    city: Short = None
    region: Short = None
    country: Short = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v is not None and not _EMAIL.fullmatch(v):
            raise ValueError("Enter an email address such as name@example.com")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is not None and (not _PHONE_CHARS.fullmatch(v) or sum(ch.isdigit() for ch in v) < 6):
            raise ValueError("Enter a phone number with digits, spaces, +, - or brackets only")
        return v

    @property
    def location(self) -> str | None:
        """ "Pune, Maharashtra, India": what a form's "Location" field wants."""
        return ", ".join(p for p in (self.city, self.region, self.country) if p) or None

    def name_or(self, fallback: str) -> str:
        return self.full_name or fallback


def contact_line(contact: ContactDetails, hint: str, links: dict[str, str]) -> str | None:
    """One line in the order the regional format asks for ("city, country, phone, email").
    None when there is neither an email nor a phone: the placeholder then stays."""
    if not (contact.email or contact.phone):
        return None
    hint = hint.lower()
    pieces: list[str] = []
    placed_location = False
    for m in re.finditer(r"address|city|town|country|phone|email|linkedin", hint):
        word = m.group(0)
        if word in ("address", "city", "town", "country"):
            if placed_location:
                continue
            placed_location = True
            parts = (
                [contact.address, " ".join(p for p in (contact.postal_code, contact.city) if p)]
                if word == "address"
                else [contact.city]
            )
            if "state" in hint or "province" in hint or word == "address":
                parts.append(contact.region)
            if "country" in hint or word == "address":
                parts.append(contact.country)
            text = ", ".join(p for p in parts if p)
            if text:
                pieces.append(text)
        elif word == "phone" and contact.phone:
            pieces.append(contact.phone)
        elif word == "email" and contact.email:
            pieces.append(contact.email)
        elif word == "linkedin" and links.get("linkedin"):
            pieces.append(re.sub(r"^https?://(www\.)?", "", links["linkedin"]).rstrip("/"))
    for value in (contact.email, contact.phone):  # always present, even if the hint forgot them
        if value and value not in pieces:
            pieces.append(value)
    return " · ".join(pieces)


DEFAULT_HINT = "city, country, phone, email"


def fill_placeholders(
    markdown: str,
    *,
    contact: ContactDetails | None,
    name: str,
    links: dict[str, str],
    answers: dict[str, str],
) -> str:
    """Replace the placeholders the user has already answered: their contact details, and
    questions in their answer bank (keys from `normalize_question`). Anything unknown stays a
    placeholder."""

    def sub(m: re.Match[str]) -> str:
        text = m.group(1).strip()
        low = text.lower()
        if contact is not None and low.startswith("contact details"):
            hint = text[text.find("(") + 1 : text.rfind(")")] if "(" in text else DEFAULT_HINT
            line = contact_line(contact, hint, links)
            if line:
                return line
        if contact is not None and low == "your name and contact details":
            line = contact_line(contact, DEFAULT_HINT, links)
            if line:
                return f"\n\n{contact.name_or(name)}  \n{line}"
        answer = answers.get(normalize_question(text))
        return answer.strip() if answer and answer.strip() else m.group(0)

    return PLACEHOLDER.sub(sub, markdown)


def read_contact(text: str) -> dict[str, str]:
    """Contact details found in a CV's header (its first lines), as suggestions only."""
    lines = [ln.strip().lstrip("#").strip().replace("**", "") for ln in text.splitlines()]
    head = [ln for ln in lines if ln][:12]
    found: dict[str, str] = {}
    if head and _looks_like_name(head[0]):
        found["full_name"] = head[0]
    joined = "\n".join(head)
    labelled: dict[str, str] = {}
    marks = list(_LABEL.finditer(joined))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(joined)
        value = joined[m.end() : end].split("\n")[0].strip(" |·•,;")
        labelled.setdefault(m.group(1).lower().replace("-", ""), value)
    if email := _EMAIL.search(labelled.get("email", "") or joined):
        found["email"] = email.group(0)
    phone_text = labelled.get("phone") or labelled.get("mobile") or labelled.get("tel")
    if phone_text and (labelled_phone := _PHONE.search(phone_text)):
        found["phone"] = labelled_phone.group(0).strip()
    else:  # an unlabelled number counts only if it can't be a year range ("2018 - 2021")
        for candidate in _PHONE.finditer(joined):
            number = candidate.group(0)
            if number.startswith("+") or sum(ch.isdigit() for ch in number) >= 10:
                found["phone"] = number.strip()
                break
    place = labelled.get("location") or labelled.get("address") or labelled.get("based in")
    if place:
        parts = [p.strip() for p in place.split(",") if p.strip()]
        if len(parts) >= 2:
            found["city"], found["country"] = parts[0], parts[-1]
        elif parts:
            found["city"] = parts[0]
    return found


def _looks_like_name(line: str) -> bool:
    words = line.split()
    return (
        2 <= len(words) <= 5
        and len(line) <= 60
        and not re.search(r"[\d@:|/]", line)
        and all(w[:1].isupper() for w in words if w.isalpha())
    )
