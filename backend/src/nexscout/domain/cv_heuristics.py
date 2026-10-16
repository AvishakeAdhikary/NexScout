"""Deterministic CV/résumé structuring: section splitting and rule-based fact extraction.

This is the M2 extractor. It is intentionally conservative:
- It copies text verbatim from the document. It never invents or rewrites claims.
- Every result carries the exact character span it came from (evidence).
- When a structure can't be determined confidently, it falls back to an `other` entry holding
  the raw text and a warning, instead of guessing.
- All results start as `extracted` + `pending` review. The user decides what is true.

An LLM-based extractor (M4) will produce the same output shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from nexscout.domain.errors import ValidationFailed
from nexscout.domain.profile import Section, validate_fact_data

METHOD = "heuristic_v1"

_HEADINGS: dict[Section, tuple[str, ...]] = {
    Section.SUMMARY: (
        "summary",
        "profile",
        "professional summary",
        "about me",
        "about",
        "objective",
        "career objective",
        "personal statement",
        "overview",
    ),
    Section.EDUCATION: (
        "education",
        "academic background",
        "qualifications",
        "academic qualifications",
        "education and training",
    ),
    Section.EMPLOYMENT: (
        "experience",
        "work experience",
        "employment",
        "professional experience",
        "employment history",
        "work history",
        "career history",
        "relevant experience",
    ),
    Section.RESEARCH: ("research experience", "research", "research projects"),
    Section.PUBLICATION: (
        "publications",
        "selected publications",
        "papers",
        "peer reviewed publications",
    ),
    Section.PROJECT: ("projects", "selected projects", "personal projects", "key projects"),
    Section.SKILL: (
        "skills",
        "technical skills",
        "core skills",
        "competencies",
        "core competencies",
        "key skills",
        "tools and technologies",
        "technologies",
        "languages and tools",
        "skills and tools",
    ),
    Section.CERTIFICATION: (
        "certifications",
        "certificates",
        "licenses",
        "licenses and certifications",
        "certifications and licenses",
    ),
    Section.AWARD: (
        "awards",
        "honors",
        "honours",
        "awards and honors",
        "awards and honours",
        "achievements",
        "scholarships",
        "honors and awards",
        "awards and scholarships",
    ),
    Section.PATENT: ("patents",),
    Section.VOLUNTEER: (
        "volunteer",
        "volunteering",
        "volunteer experience",
        "community involvement",
        "community service",
    ),
    Section.LEADERSHIP: (
        "leadership",
        "extracurricular activities",
        "activities",
        "leadership and activities",
        "leadership experience",
    ),
    Section.MEMBERSHIP: (
        "professional affiliations",
        "memberships",
        "affiliations",
        "professional memberships",
    ),
    Section.REFERENCE: ("references", "referees"),
}
_HEADING_LOOKUP = {h: s for s, hs in _HEADINGS.items() for h in hs}

_MONTHS = {
    m: i
    for i, ms in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in ms
}
_MONTH_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
_DATE_RE = rf"(?:(?:{_MONTH_RE}\s+)?(?:19|20)\d{{2}}|(?:0?[1-9]|1[0-2])/(?:19|20)\d{{2}})"
_RANGE = re.compile(
    rf"(?P<start>{_DATE_RE})\s*(?:-|–|—|to|until)\s*(?P<end>{_DATE_RE}|present|current|now|today)",
    re.IGNORECASE,
)
_SINGLE_DATE = re.compile(_DATE_RE, re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦‣●–]|\d{1,2}[.)])\s+")
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;]+")
_URL = re.compile(r"https?://[^\s<>()]+")

_TITLE_WORDS = re.compile(
    r"\b(engineer|developer|manager|analyst|intern|assistant|scientist|researcher|lead|head|"
    r"director|consultant|specialist|officer|associate|teacher|professor|lecturer|designer|"
    r"architect|administrator|coordinator|technician|fellow|postdoc\w*|tutor|instructor|"
    r"founder|co-founder|ceo|cto|vp|president|editor|writer|nurse|accountant|programmer|"
    r"advisor|adviser|trainee|apprentice|executive|representative|supervisor|student)\b",
    re.IGNORECASE,
)
_INSTITUTION_WORDS = re.compile(
    r"\b(university|universit[äa]t|universidad|universit[ée]|college|institute|institut|school|"
    r"academy|polytechnic|politecnico|[ée]cole|faculty|iit|mit|eth)\b",
    re.IGNORECASE,
)
_DEGREE_RE = re.compile(
    r"\b(ph\.?\s?d\.?|d\.?phil|doctorate|doctor of [a-z ]+|m\.?\s?sc\.?|m\.?\s?eng\.?|"
    r"m\.?\s?tech\.?|m\.?\s?a\.?|mba|m\.?\s?phil\.?|master(?:'s)?(?: of [a-z ]+)?|"
    r"b\.?\s?sc\.?|b\.?\s?eng\.?|"
    r"b\.?\s?tech\.?|b\.?\s?a\.?|b\.?\s?s\.?|bachelor(?:'s)?(?: of [a-z ]+)?|diploma|"
    r"associate degree|high school|a-levels|gcse|certificate)\b",
    re.IGNORECASE,
)
_SEPARATORS = re.compile(r"\s+(?:—|–|-|\||@|·|•)\s+|,\s+|\s+at\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    text: str
    start: int  # char offset in the full document text
    end: int


@dataclass(frozen=True)
class Block:
    section: Section
    heading: str | None
    lines: list[Line]

    @property
    def start(self) -> int:
        return self.lines[0].start if self.lines else 0

    @property
    def end(self) -> int:
        return self.lines[-1].end if self.lines else 0


@dataclass
class ExtractedFact:
    section: Section
    data: dict[str, Any]
    start: int
    end: int
    excerpt: str
    warnings: list[str] = field(default_factory=list)
    confidence: str = "medium"  # "low" | "medium": always needs user review


def _lines(text: str) -> list[Line]:
    out: list[Line] = []
    pos = 0
    for raw in text.split("\n"):
        out.append(Line(raw, pos, pos + len(raw)))
        pos += len(raw) + 1
    return out


def heading_section(line: str) -> Section | None:
    cleaned = re.sub(r"^[#*_\s]+|[*_:\s]+$", "", line).strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned.replace("&", "and"))
    if not cleaned or len(cleaned.split()) > 6:
        return None
    return _HEADING_LOOKUP.get(cleaned)


def split_sections(text: str) -> list[Block]:
    """Split text into blocks at recognized headings. Text before the first heading is skipped
    (it is usually the name and contact details, which are not turned into facts)."""
    blocks: list[Block] = []
    current: Block | None = None
    for line in _lines(text):
        section = heading_section(line.text)
        if section is not None:
            current = Block(section=section, heading=line.text.strip(), lines=[])
            blocks.append(current)
        elif current is not None:
            current.lines.append(line)
    for block in blocks:  # trim leading/trailing blank lines
        while block.lines and not block.lines[0].text.strip():
            block.lines.pop(0)
        while block.lines and not block.lines[-1].text.strip():
            block.lines.pop()
    return [b for b in blocks if b.lines]


# ------------------------------------------------------------------------------- dates
def to_partial_date(token: str) -> str | None:
    t = token.strip().lower().rstrip(".")
    if t in {"present", "current", "now", "today"}:
        return "present"
    m = re.fullmatch(r"(0?[1-9]|1[0-2])/((?:19|20)\d{2})", t)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.fullmatch(rf"(?:({_MONTH_RE})\s+)?((?:19|20)\d{{2}})", t, re.IGNORECASE)
    if not m:
        return None
    year = m.group(2)
    if m.group(1):
        key = m.group(1).lower().rstrip(".")
        month = _MONTHS.get(key) or _MONTHS.get(key[:3])
        if month:
            return f"{year}-{month:02d}"
    return year


def find_range(text: str) -> tuple[str | None, str | None, tuple[int, int] | None]:
    m = _RANGE.search(text)
    if not m:
        return None, None, None
    return to_partial_date(m.group("start")), to_partial_date(m.group("end")), m.span()


def _strip_span(text: str, span: tuple[int, int] | None) -> str:
    if span is None:
        return text.strip()
    out = (text[: span[0]] + text[span[1] :]).strip()
    return re.sub(r"[\s,|·•()\[\]–—-]+$", "", re.sub(r"^[\s,|·•()\[\]–—-]+", "", out)).strip()


def _clean_item(text: str) -> str:
    return _BULLET.sub("", text).strip()


# ------------------------------------------------------------------------------- entries
def _entries(block: Block) -> list[list[Line]]:
    """Split a dated block into entries: blank lines, or a new non-bullet line with a date range
    when the current entry already has one."""
    entries: list[list[Line]] = []
    current: list[Line] = []
    current_has_range = False
    for line in block.lines:
        stripped = line.text.strip()
        if not stripped:
            if current:
                entries.append(current)
                current, current_has_range = [], False
            continue
        is_bullet = bool(_BULLET.match(line.text))
        has_range = _RANGE.search(stripped) is not None
        if current and has_range and not is_bullet and current_has_range:
            entries.append(current)
            current, current_has_range = [], False
        current.append(line)
        current_has_range = current_has_range or has_range
    if current:
        entries.append(current)
    return entries


def _split_parts(header: str) -> list[str]:
    return [p.strip() for p in _SEPARATORS.split(header) if p and p.strip()]


def _entry_header(entry: list[Line]) -> tuple[str, str | None, str | None, list[str], list[Line]]:
    """Return (header_text, start, end, extra_header_parts, body_lines)."""
    first = entry[0].text.strip()
    start, end, span = find_range(first)
    header = _clean_item(_strip_span(first, span))
    body = entry[1:]
    extra: list[str] = []
    # A dateless first line followed by a dated, non-bullet second line: both are header lines
    # ("Acme Corp" / "Software Engineer   2019 - 2021").
    if body and not _BULLET.match(body[0].text):
        s2, e2, span2 = find_range(body[0].text)
        if start is None and s2 is not None:
            start, end = s2, e2
            extra.append(_clean_item(_strip_span(body[0].text, span2)))
            body = body[1:]
        elif start is not None and len(_split_parts(header)) < 2 and body[0].text.strip():
            # "Software Engineer  2019-2021" / "Acme Corp"
            if not _RANGE.search(body[0].text) and len(body[0].text.strip()) <= 120:
                extra.append(_clean_item(body[0].text))
                body = body[1:]
    return header, start, end, [e for e in extra if e], body


def _description(lines: list[Line]) -> str | None:
    text = "\n".join(_clean_item(ln.text) for ln in lines if ln.text.strip())
    return text[:5000] or None


def _excerpt(text: str, start: int, end: int) -> str:
    return text[start:end][:1000]


def _validated(section: Section, data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return validate_fact_data(section, data)
    except ValidationFailed:
        return None


def _fallback(full: str, entry: list[Line], reason: str) -> ExtractedFact:
    start, end = entry[0].start, entry[-1].end
    first = _clean_item(entry[0].text)[:500] or "Untitled entry"
    data = {"title": first, "description": _description(entry[1:])}
    return ExtractedFact(
        Section.OTHER,
        validate_fact_data(Section.OTHER, data),
        start,
        end,
        _excerpt(full, start, end),
        [reason],
        "low",
    )


def _employment(full: str, entry: list[Line]) -> ExtractedFact:
    header, start, end, extra, body = _entry_header(entry)
    parts = _split_parts(header) + extra
    warnings: list[str] = []
    title = org = None
    if len(parts) >= 2:
        a, b = parts[0], parts[1]
        if _TITLE_WORDS.search(b) and not _TITLE_WORDS.search(a):
            title, org = b, a
        else:
            title, org = a, b
            if not _TITLE_WORDS.search(a):
                warnings.append("Check which part is the job title and which is the organization.")
    if not title or not org:
        return _fallback(full, entry, "Couldn't tell the job title and organization apart.")
    data = _validated(
        Section.EMPLOYMENT,
        {
            "title": title[:500],
            "organization": org[:500],
            "start": start,
            "end": end,
            "description": _description(body),
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = entry[0].start, entry[-1].end
    return ExtractedFact(
        Section.EMPLOYMENT,
        data,
        s,
        e,
        _excerpt(full, s, e),
        warnings,
        "low" if warnings else "medium",
    )


def _education(full: str, entry: list[Line]) -> ExtractedFact:
    header, start, end, extra, body = _entry_header(entry)
    parts = _split_parts(header) + extra
    institution = next((p for p in parts if _INSTITUTION_WORDS.search(p)), None)
    degree_part = next((p for p in parts if _DEGREE_RE.search(p) and p != institution), None)
    warnings: list[str] = []
    if institution is None:
        candidates = [p for p in parts if p != degree_part]
        if not candidates:
            return _fallback(full, entry, "Couldn't find the institution name.")
        institution = candidates[0]
        warnings.append("Check the institution name.")
    degree = field_of_study = None
    if degree_part:
        m = re.match(r"(?P<deg>.+?)\s+(?:in|of)\s+(?P<field>.+)$", degree_part, re.IGNORECASE)
        if m and _DEGREE_RE.search(m.group("deg")):
            degree, field_of_study = m.group("deg").strip(), m.group("field").strip()
        else:
            degree = degree_part
    data = _validated(
        Section.EDUCATION,
        {
            "institution": institution[:500],
            "degree": degree,
            "field_of_study": field_of_study,
            "start": start,
            "end": end,
            "description": _description(body),
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = entry[0].start, entry[-1].end
    return ExtractedFact(
        Section.EDUCATION,
        data,
        s,
        e,
        _excerpt(full, s, e),
        warnings,
        "low" if warnings else "medium",
    )


def _role_at_org(full: str, entry: list[Line], section: Section) -> ExtractedFact:
    header, start, end, extra, body = _entry_header(entry)
    parts = _split_parts(header) + extra
    if not parts:
        return _fallback(full, entry, "Couldn't read this entry.")
    role, org = (parts[0], parts[1]) if len(parts) >= 2 else (None, parts[0])
    if section is Section.RESEARCH:
        payload: dict[str, Any] = {
            "title": header[:500] or parts[0][:500],
            "organization": extra[0][:500] if extra else None,
            "start": start,
            "end": end,
            "description": _description(body),
        }
    else:
        payload = {
            "organization": org[:500],
            "role": role[:500] if role else None,
            "start": start,
            "end": end,
            "description": _description(body),
        }
    data = _validated(section, payload)
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = entry[0].start, entry[-1].end
    return ExtractedFact(section, data, s, e, _excerpt(full, s, e))


def _project(full: str, entry: list[Line]) -> ExtractedFact:
    header, start, end, extra, body = _entry_header(entry)
    url = _URL.search(" ".join(ln.text for ln in entry))
    data = _validated(
        Section.PROJECT,
        {
            "name": (header or (extra[0] if extra else ""))[:500],
            "start": start,
            "end": end,
            "description": _description(body),
            "url": url.group(0) if url else None,
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this project entry.")
    s, e = entry[0].start, entry[-1].end
    return ExtractedFact(Section.PROJECT, data, s, e, _excerpt(full, s, e))


def _list_items(block: Block) -> list[Line]:
    """Each non-empty line is an item; wrapped continuation lines are joined to the previous one."""
    items: list[Line] = []
    for line in block.lines:
        if not line.text.strip():
            continue
        if items and not _BULLET.match(line.text) and line.text.startswith((" ", "\t")):
            prev = items[-1]
            items[-1] = Line(prev.text + " " + line.text.strip(), prev.start, line.end)
        else:
            items.append(line)
    return items


def _skills(full: str, block: Block) -> list[ExtractedFact]:
    out: list[ExtractedFact] = []
    seen: set[str] = set()
    for line in _list_items(block):
        raw = _clean_item(line.text)
        category = None
        if ":" in raw and raw.index(":") < 40:
            category, raw = (x.strip() for x in raw.split(":", 1))
        for item in re.split(r"\s*[,;|•·]\s*|\s+/\s+", raw):
            name = item.strip().strip(".")
            if not name or len(name) > 120 or name.lower() in seen:
                continue
            seen.add(name.lower())
            data = _validated(Section.SKILL, {"name": name, "category": category or None})
            if data:
                out.append(
                    ExtractedFact(
                        Section.SKILL,
                        data,
                        line.start,
                        line.end,
                        _excerpt(full, line.start, line.end),
                    )
                )
    return out


def _simple_items(full: str, block: Block) -> list[ExtractedFact]:
    out: list[ExtractedFact] = []
    for line in _list_items(block):
        raw = _clean_item(line.text)
        if not raw:
            continue
        section = block.section
        payload: dict[str, Any]
        if section is Section.PUBLICATION:
            year = _YEAR.search(raw)
            doi = _DOI.search(raw)
            url = _URL.search(raw)
            payload = {
                "title": raw[:500],
                "year": year.group(0) if year else None,
                "doi": doi.group(0).rstrip(".") if doi else None,
                "url": url.group(0) if url else None,
            }
        elif section in (Section.CERTIFICATION, Section.AWARD):
            m = _SINGLE_DATE.search(raw)
            date = to_partial_date(m.group(0)) if m else None
            name = _strip_span(raw, m.span()) if m else raw
            payload = {"name": (name or raw)[:500], "date": date}
        elif section is Section.PATENT:
            payload = {"title": raw[:500]}
        elif section is Section.REFERENCE:
            if re.search(r"available (up)?on request", raw, re.IGNORECASE):
                continue
            payload = {"name": raw[:500]}
        else:
            payload = {"title": raw[:500]}
            section = Section.OTHER
        data = _validated(section, payload)
        if data:
            out.append(
                ExtractedFact(
                    section, data, line.start, line.end, _excerpt(full, line.start, line.end)
                )
            )
    return out


def extract_facts(text: str) -> list[ExtractedFact]:
    """Run the full heuristic pipeline over normalized document text."""
    facts: list[ExtractedFact] = []
    for block in split_sections(text):
        section = block.section
        if section is Section.SUMMARY:
            body = "\n".join(ln.text.strip() for ln in block.lines).strip()
            data = _validated(Section.SUMMARY, {"text": body[:5000]})
            if data:
                facts.append(
                    ExtractedFact(
                        section,
                        data,
                        block.start,
                        block.end,
                        _excerpt(text, block.start, block.end),
                    )
                )
        elif section is Section.SKILL:
            facts.extend(_skills(text, block))
        elif section in (
            Section.PUBLICATION,
            Section.CERTIFICATION,
            Section.AWARD,
            Section.PATENT,
            Section.REFERENCE,
        ):
            facts.extend(_simple_items(text, block))
        else:
            for entry in _entries(block):
                if section is Section.EMPLOYMENT:
                    facts.append(_employment(text, entry))
                elif section is Section.EDUCATION:
                    facts.append(_education(text, entry))
                elif section is Section.PROJECT:
                    facts.append(_project(text, entry))
                else:
                    facts.append(_role_at_org(text, entry, section))
    return facts
