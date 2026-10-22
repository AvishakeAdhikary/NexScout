"""Recommendation letters: who recommends you, read from the letter (pure, deterministic).

A letter is about the candidate but written by someone else, so nothing in it becomes a claim
about the candidate. What it does establish is a **reference**: the recommender's name, position,
organization, contact and how they know the candidate. That is read from the signature block
(the last block of short lines, after "Sincerely"/"Regards" when present) and from the sentence
that states the relationship ("I have known him since 2018 as my student"). The result is one
pending, private reference entry with the signature block as its evidence; the user reviews it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from nexscout.domain.errors import ValidationFailed
from nexscout.domain.profile import Section, validate_fact_data

METHOD = "letter_v1"

_CLOSING = re.compile(
    r"^\s*(?:yours\s+(?:sincerely|faithfully|truly)|sincerely(?:\s+yours)?|(?:kind|best|warm|"
    r"warmest)\s+regards|regards|with\s+(?:best|kind|warm)\s+(?:regards|wishes)|best\s+wishes|"
    r"respectfully(?:\s+yours)?|thanking\s+you|thank\s+you)\s*,?\s*$",
    re.IGNORECASE,
)
_TITLE_WORDS = re.compile(
    r"\b(professor|lecturer|principal|dean|director|head|chair|chairperson|manager|engineer|"
    r"scientist|researcher|supervisor|advisor|adviser|coordinator|president|vice|founder|ceo|"
    r"cto|lead|officer|teacher|faculty|registrar|hod|reader|fellow)\b",
    re.IGNORECASE,
)
_ORG_WORDS = re.compile(
    r"\b(university|college|institute|institution|school|academy|polytechnic|laboratory|lab|"
    r"department|faculty|centre|center|foundation|hospital|company|corporation|inc|ltd|gmbh|"
    r"technologies|limited)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\+?\d[\d\s()-]{7,}\d)")
_CREDENTIALS = re.compile(
    r"^(?:ph\.?\s?d|m\.?\s?tech|b\.?\s?tech|m\.?\s?sc|mba|post\s?doc|d\.?\s?sc)\b", re.IGNORECASE
)
_NAME_LINE = re.compile(
    r"^(?:(?:dr|prof|professor|mr|mrs|ms|mx)\.?\s+)*[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,4}"
    r"(?:\s*,\s*[^,]{1,40})?$"
)
# The specific role, most informative first: "as his professor and academic advisor",
# "as my student".
_ROLE = (
    r"(?:professor|teacher|supervisor|advisor|adviser|mentor|manager|guide|instructor|lecturer|"
    r"principal|head|employer|team lead|student|phd student|research assistant|mentee|employee|"
    r"colleague)"
)
_ROLE_PHRASE = re.compile(
    rf"\bas (?:his|her|their|my) (?:\w+ ){{0,2}}{_ROLE}(?: and (?:\w+ ){{0,2}}{_ROLE})?\b"
    rf"|\b(?:was|is) my (?:\w+ ){{0,2}}{_ROLE}\b",
    re.IGNORECASE,
)
_SALUTATION = re.compile(
    r"^\s*(?:to whom it may concern|dear\b.*|letter of (?:recommendation|reference)|"
    r"recommendation letter|reference letter)\s*[:,]?\s*$",
    re.IGNORECASE,
)
_RELATIONSHIP = re.compile(
    r"\b(as (?:his|her|their) (?:professor|teacher|supervisor|advisor|adviser|mentor|manager|"
    r"guide|instructor|lecturer|principal|head|employer|team lead)|(?:was|is) my (?:student|"
    r"phd student|research assistant|mentee|employee|colleague)|as my student|"
    r"i have known (?:him|her|them)|i know (?:him|her|them)|whom i (?:have )?know|"
    r"i (?:have )?taught|i (?:have )?supervised|under my (?:guidance|supervision)|"
    r"worked (?:with|under|for) me|in my (?:class|course|lab|laboratory|team|group))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LetterReference:
    data: dict[str, object]
    start: int  # evidence span: the signature block
    end: int
    excerpt: str
    relationship_quote: str | None
    warnings: list[str]


_ORG_RANK = (
    re.compile(r"\b(university|universit[äa]t|college|polytechnic)\b", re.I),
    re.compile(
        r"\b(institute|institution|academy|hospital|laboratory|company|corporation|"
        r"inc|ltd|gmbh|limited|technologies)\b",
        re.I,
    ),
    _ORG_WORDS,
)


def _best_org(parts: list[str]) -> str | None:
    """The organization among signature parts: a university before its school or department."""
    for pattern in _ORG_RANK:
        for p in parts:
            if pattern.search(p):
                words = p.split()
                # "Example University Pune Example" / "Education Group": the line wrapped into the
                # parent group's name, which starts with the same word. Drop that start.
                if len(words) > 2 and words[-1] == words[0]:
                    words = words[:-1]
                return " ".join(words)
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def _lines(text: str) -> list[tuple[str, int, int]]:
    out, pos = [], 0
    for raw in text.split("\n"):
        out.append((raw, pos, pos + len(raw)))
        pos += len(raw) + 1
    return out


def _signature_block(lines: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """Lines after the last closing phrase; otherwise the last block of non-empty lines."""
    for i in range(len(lines) - 1, -1, -1):
        if _CLOSING.match(lines[i][0]):
            return [ln for ln in lines[i + 1 :] if ln[0].strip()][:10]
    block: list[tuple[str, int, int]] = []
    for ln in reversed(lines):
        if ln[0].strip():
            block.append(ln)
        elif block:
            break
    return list(reversed(block))[:10]


def _sentences(text: str) -> list[str]:
    flat = _norm(text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", flat) if s.strip()]


def read_reference(text: str) -> LetterReference | None:
    """The recommender as a reference entry, or None when no signature can be found."""
    lines = _lines(text)
    block = _signature_block(lines)
    if not block:
        return None
    name = title = org = None
    warnings: list[str] = []
    rest: list[str] = []
    for raw, _s, _e in block:
        line = _norm(raw)
        if name is None:
            if _EMAIL.search(line) or (_TITLE_WORDS.search(line) and "," not in line):
                warnings.append("The signature doesn't start with a name; check it.")
            candidate = re.split(r"\s*,\s*", line, maxsplit=1)[0]  # "Name, PhD (CSE)"
            if _NAME_LINE.match(line) or _NAME_LINE.match(candidate):
                name = candidate.strip()
                continue
        rest.append(line)
    if not name:
        return None
    for line in rest:
        if _CREDENTIALS.match(line) or (_EMAIL.search(line) and not _TITLE_WORDS.search(line)):
            continue
        if title is None and _TITLE_WORDS.search(line):
            parts = [p.strip() for p in re.split(r"\s*[|,]\s*", line) if p.strip()]
            title = parts[0]
            org = _best_org(parts[1:]) or org
            continue
        if org is None and _ORG_WORDS.search(line):
            org = _best_org(re.split(r"\s*\|\s*", line))
    block_text = "\n".join(raw for raw, _s, _e in block)
    # The recommender's own contact (signature) before the letterhead's general address.
    emails, phones = _EMAIL.findall(block_text), _PHONE.findall(block_text)
    contact = (
        emails[0]
        if emails
        else phones[0].strip()
        if phones
        else next(iter(_EMAIL.findall(text)), None)
    )
    # Only the letter's body: after the salutation, before the signature.
    first_body = 0
    for i, (raw, _s, _e) in enumerate(lines):
        if _SALUTATION.match(raw):
            first_body = i + 1
    body_end = block[0][1]
    body = "\n".join(raw for raw, s, _e in lines[first_body:] if s < body_end)
    sentences = _sentences(body)
    quote = next((s for s in sentences if _ROLE_PHRASE.search(s)), None) or next(
        (s for s in sentences if _RELATIONSHIP.search(s)), None
    )
    relationship = None
    if quote:
        m = _ROLE_PHRASE.search(quote) or _RELATIONSHIP.search(quote)
        relationship = _norm(m.group(0)) if m else None
    if title is None:
        warnings.append("Couldn't find the recommender's position.")
    payload = {
        "name": name[:200],
        # The recommender's position, then the letter's own words for how they know you.
        "relationship": " — ".join(
            x for x in (title, f'"{relationship}"' if relationship else None) if x
        )
        or None,
        "organization": org[:300] if org else None,
        "contact": contact,
    }
    try:
        data = validate_fact_data(Section.REFERENCE, payload)
    except ValidationFailed:
        return None
    start, end = block[0][1], block[-1][2]
    return LetterReference(
        data, start, end, text[start:end][:1000], quote[:400] if quote else None, warnings
    )
