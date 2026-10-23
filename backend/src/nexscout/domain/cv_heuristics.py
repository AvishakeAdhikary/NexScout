"""Deterministic CV/résumé structuring: section splitting and rule-based fact extraction.

Conservative by design:
- It copies text from the document. It never invents or rewrites claims.
- Every result carries the exact character span it came from (evidence). Field values are cleaned
  (Markdown markers removed, ligatures normalized); the evidence span stays the original text.
- When a structure can't be determined confidently, it falls back to an `other` entry holding
  the raw text and a warning, instead of guessing. Implausible fragments are dropped.
- All results start as `extracted` + `pending` review. The user decides what is true.

v2 (M18, from a real CV): understands Markdown CVs (`##` sections, `###` entries, italic date
lines, `**Category:**` skill lists) and the text pypdf produces from the same CV exported to PDF
(wrapped lines without indentation, `•` bullets, ligatures). Skill lists split only at top-level
separators ("JavaScript (React.js, Angular)" is three skills, not "JavaScript (React.js" and
"Angular)"). Projects and certifications are linked to the job they belong to when the CV says so.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from nexscout.domain.errors import ValidationFailed
from nexscout.domain.profile import Section, validate_fact_data

METHOD = "heuristic_v2"

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
        "professional profile",
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
    Section.PROJECT: (
        "projects",
        "selected projects",
        "personal projects",
        "key projects",
        "open source projects",
        "open-source projects",
    ),
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
# Spoken languages become skills in this category (the profile has no separate section).
_SPOKEN_HEADINGS = frozenset({"languages", "language skills", "spoken languages", "language"})
SPOKEN_CATEGORY = "Spoken languages"

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
# A line that is only dates (and "| place | org" extras): the date line under an entry header.
_DATE_LINE = re.compile(
    rf"^\s*[*_]*\s*(?:{_RANGE.pattern}|{_DATE_RE})\s*(?:[|,·•]|[*_]*\s*$)", re.IGNORECASE
)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦‣●–]|\d{1,2}[.)])\s+")
_MD_HEADING = re.compile(r"^\s*(#{1,6})\s+")
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;]+")
_URL = re.compile(r"https?://[^\s<>()\]]+")
_URL_TAIL = re.compile(r"[\w.~%/-]+")
# A bare lowercase domain on a project's date line ("example.ai", "example.org/app").
_DOMAIN = re.compile(r"[a-z0-9][a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,10}(?:/[^\s|]*)?")
_BARE_URL = re.compile(
    r"(?<![\w@/])(?:www\.)?(?:github\.com|gitlab\.com|huggingface\.co|[a-z0-9-]+\.github\.io)"
    r"(?:/[^\s<>()|\]*]+)?",
    re.IGNORECASE,
)

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
    r"m\.?\s?tech\.?|m\.?\s?a\.?|mba|mca|bca|m\.?\s?phil\.?|master(?:'s)?(?: of [a-z ]+)?|"
    r"b\.?\s?sc\.?|b\.?\s?eng\.?|"
    r"b\.?\s?tech\.?|b\.?\s?a\.?|b\.?\s?s\.?|bachelor(?:'s)?(?: of [a-z ]+)?|diploma|"
    r"associate degree|high school|a-levels|gcse|certificate)\b",
    re.IGNORECASE,
)
_SEPARATORS = re.compile(r"\s+(?:—|–|--|-|\||@|·|•)\s+|,\s+|\s+at\s+", re.IGNORECASE)
# "Title - Organization" / "Name -- tagline" / "Name — Issuer": the main split in a header.
_DASH_SPLIT = re.compile(r"\s+(?:--|—|–|-)\s+")
_TECH_LINE = re.compile(r"^(?:tech(?:nologies|nology)?|stack|tools|built with)\s*:\s*", re.I)


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
    spoken_languages: bool = False

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
    # Indexes (into the list extract_facts returns) of entries this one belongs to: a project
    # done in a job, a certification earned in one. Saved as `related_fact_ids`.
    related: list[int] = field(default_factory=list)
    org_hint: str | None = None  # the organization a project/cert names on its date line


# ------------------------------------------------------------------------------ text helpers
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://)?[^)\s]+\)")
_MD_EMPH = re.compile(r"(\*\*|__)(.+?)\1")
_MD_ITAL = re.compile(r"(?<![\w*])([*_])(?=\S)(.+?)(?<=\S)\1(?![\w*])")


def clean(text: str) -> str:
    """A field value without Markdown markup, ligatures or stray emphasis markers."""
    s = unicodedata.normalize("NFKC", text)
    s = _MD_LINK.sub(r"\1", s)
    s = s.replace("`", "")
    for _ in range(2):
        s = _MD_EMPH.sub(r"\2", s)
        s = _MD_ITAL.sub(r"\2", s)
    s = _MD_HEADING.sub("", s)
    s = re.sub(r"^\s*(?:\*\*|__|[*_])+\s*|\s*(?:\*\*|__|[*_])+\s*$", "", s)
    s = s.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", s).strip()


def _lines(text: str) -> list[Line]:
    out: list[Line] = []
    pos = 0
    for raw in text.split("\n"):
        out.append(Line(raw, pos, pos + len(raw)))
        pos += len(raw) + 1
    return out


def _is_bullet(line: Line) -> bool:
    return bool(_BULLET.match(line.text)) and not _MD_HEADING.match(line.text)


def _is_date_line(line: Line) -> bool:
    return bool(_DATE_LINE.match(clean(line.text)))


def heading_section(line: str) -> Section | None:
    return _heading(line)[0]


def _heading(line: str) -> tuple[Section | None, bool]:
    """(section, is_spoken_languages) for a heading line, else (None, False)."""
    raw = line.strip()
    if not raw or (_BULLET.match(raw) and not raw.startswith("**")):
        return None, False
    cleaned = re.sub(r"^[#*_\s]+|[*_:\s]+$", "", unicodedata.normalize("NFKC", raw)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned.replace("&", "and")).lower()
    if not cleaned or len(cleaned.split()) > 6:
        return None, False
    if cleaned in _SPOKEN_HEADINGS:
        return Section.SKILL, True
    return _HEADING_LOOKUP.get(cleaned), False


def split_sections(text: str) -> list[Block]:
    """Split text into blocks at recognized headings. Text before the first heading is skipped
    (it is usually the name and contact details, which are not turned into facts)."""
    blocks: list[Block] = []
    current: Block | None = None
    for line in _lines(text):
        section, spoken = _heading(line.text)
        if section is not None:
            current = Block(section, line.text.strip(), [], spoken)
            blocks.append(current)
        elif current is not None and not re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line.text):
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
    return clean(_BULLET.sub("", text))


# --------------------------------------------------------------------- logical structure
def _wraps_inside_word(text: str) -> bool:
    """Did the line break fall inside a word or URL ("github.com/", "MCP-", "2018-")?"""
    return text.endswith("/") or (len(text) > 1 and text[-1] in "-–" and text[-2].isalnum())


@dataclass
class _Item:
    """A logical line: a bullet (or plain line) with its wrapped continuation lines joined."""

    lines: list[Line]
    bullet: bool

    @property
    def text(self) -> str:
        out = ""
        for ln in self.lines:
            part = ln.text.strip()
            out = out + part if _wraps_inside_word(out) else (f"{out} {part}" if out else part)
        return out

    @property
    def start(self) -> int:
        return self.lines[0].start

    @property
    def end(self) -> int:
        return self.lines[-1].end


def _continues(prev: str, line: str) -> bool:
    """Is `line` the rest of `prev`'s sentence even though a blank line sits between them?
    PDF text often has a blank line inside a wrapped bullet ("...integrating AI," / "" /
    "telemedicine, and ..."). It is when the line starts in lower case or with closing/
    continuing punctuation, or when `prev` stops mid-list (a trailing comma, "and", "&")."""
    nxt = line.strip()
    before = prev.rstrip()
    if not nxt or not before or _BULLET.match(line) or _MD_HEADING.match(line):
        return False
    return (
        nxt[0].islower()
        or nxt[0] in "(),;&"
        or before.endswith((",", "&", "/", "-", "("))
        or before.lower().endswith((" and", " or", " of", " the", " with", " for"))
    )


def _items(lines: list[Line], *, join_plain: bool = True) -> list[_Item]:
    """Group lines into items. A non-bullet line continues the previous item when it is
    indented (Markdown wrap) or follows a bullet without a blank line (PDF wrap)."""
    out: list[_Item] = []
    prev_blank = True
    for ln in lines:
        if not ln.text.strip():
            prev_blank = True
            continue
        if _is_bullet(ln):
            out.append(_Item([ln], True))
        elif (
            out
            and not prev_blank
            and (out[-1].bullet or (join_plain and ln.text[:1] in (" ", "\t")))
            and not _MD_HEADING.match(ln.text)
        ) or (out and prev_blank and _continues(out[-1].lines[-1].text, ln.text)):
            out[-1].lines.append(ln)
        else:
            out.append(_Item([ln], False))
        prev_blank = False
    return out


@dataclass
class _Entry:
    lines: list[Line]


def _entries(block: Block) -> list[_Entry]:
    """Split a dated block into entries. A new entry starts at a `###` heading, after a blank
    line, at a header run (non-bullet lines followed by a date line within two lines), or at a
    new dated non-bullet line when the current entry already has dates."""
    lines = block.lines
    starts: set[int] = set()
    n = len(lines)
    for i, ln in enumerate(lines):
        text = ln.text.strip()
        if not text:
            continue
        if _MD_HEADING.match(ln.text):
            starts.add(i)
            continue
        if i == 0:
            starts.add(i)
            continue
        if not lines[i - 1].text.strip() and not _is_bullet(ln):
            k = next((k for k in range(i - 1, -1, -1) if lines[k].text.strip()), -1)
            prev_text = lines[k].text if k >= 0 else ""
            # A date line after a blank still belongs to a header line standing alone above it
            # ("EdgeCam" / "" / "March 2025 - Present | Independent").
            header_above = (
                k in starts
                and _is_date_line(ln)
                and not _is_bullet(lines[k])
                and not _is_date_line(lines[k])
            )
            if not header_above and not _continues(prev_text, ln.text):
                starts.add(i)
                continue
        if _is_bullet(ln) or _is_date_line(ln):
            continue
        # A header run: this line (and maybe one more) then a date line.
        prev = lines[i - 1]
        prev_is_header_part = not _is_bullet(prev) and not _is_date_line(prev) and (i - 1) in starts
        if prev_is_header_part:
            continue
        if (
            i + 2 < n
            and not lines[i + 1].text.strip()
            and _is_date_line(lines[i + 2])
            and len(text) <= 80
            and text[:1].isupper()
            and not re.search(r"[.;:!?,]\s*$", text)
        ):
            starts.add(i)  # a title, a blank line (PDF text), then its date line
            continue
        for j in (i + 1, i + 2):
            if j < n and _is_date_line(lines[j]):
                between = lines[i + 1 : j]
                # A two-line header ("Master of ... - Example" / "University Pune"): the first
                # line doesn't end a sentence and the second is a short capitalized fragment.
                # This keeps a wrapped bullet's last line ("deployment time by 25%.") out.
                two_line_ok = not between or (
                    not re.search(r"[.;:!?]\s*$", text)
                    and len(between[0].text.strip()) <= 60
                    and between[0].text.strip()[:1].isupper()
                )
                if two_line_ok and all(b.text.strip() and not _is_bullet(b) for b in between):
                    starts.add(i)
                break
            if j < n and (_is_bullet(lines[j]) or not lines[j].text.strip()):
                break
    out: list[_Entry] = []
    current: list[Line] = []
    has_range = False
    for i, ln in enumerate(lines):
        if not ln.text.strip():
            continue
        dated_header = (
            not _is_bullet(ln) and not _is_date_line(ln) and _RANGE.search(ln.text) is not None
        )
        if current and (i in starts or (dated_header and has_range)):
            out.append(_Entry(current))
            current, has_range = [], False
        current.append(ln)
        has_range = has_range or _RANGE.search(ln.text) is not None
    if current:
        out.append(_Entry(current))
    return out


@dataclass
class _Header:
    text: str  # cleaned header (dates removed)
    start: str | None
    end: str | None
    extras: list[str]  # "| place | org" parts of the date line, cleaned
    body: list[_Item]  # everything after the header, as logical items
    lead: list[str]  # plain text right after the date line (not a bullet)


def _parse_header(entry: _Entry) -> _Header:
    lines = entry.lines
    header_lines: list[Line] = []
    i = 0
    while i < len(lines) and not _is_bullet(lines[i]) and not _is_date_line(lines[i]):
        header_lines.append(lines[i])
        i += 1
        if len(header_lines) == 2 or _RANGE.search(header_lines[-1].text):
            break
    date_line: Line | None = None
    if i < len(lines) and _is_date_line(lines[i]):
        date_line = lines[i]
        i += 1
    header = clean(" ".join(ln.text.strip() for ln in header_lines))
    start = end = None
    extras: list[str] = []
    if date_line is not None:
        dtext = clean(date_line.text)
        s, e, span = find_range(dtext)
        if span is None:
            m = _SINGLE_DATE.search(dtext)
            if m:
                s = to_partial_date(m.group(0))
                span = m.span()
        start, end = s, e
        rest = dtext[span[1] :] if span else dtext
        extras = [p.strip() for p in re.split(r"\s*[|·•]\s*", rest) if p.strip()]
        # "... | Example University Pune |" then the link on the next line.
        if re.search(r"[|·]\s*$", dtext) and i < len(lines) and not _is_bullet(lines[i]):
            more = clean(lines[i].text)
            if _URL.search(more) or _BARE_URL.search(more) or _DOMAIN.fullmatch(more):
                extras += [p.strip() for p in re.split(r"\s*[|·•]\s*", more) if p.strip()]
                i += 1
        # A link at the end of the date line that the PDF wrapped ("github.com/Name/" / "repo").
        while (
            extras
            and _wraps_inside_word(extras[-1])
            and (_URL.search(extras[-1]) or _BARE_URL.search(extras[-1]))
            and i < len(lines)
            and _URL_TAIL.fullmatch(lines[i].text.strip())
        ):
            extras[-1] += lines[i].text.strip()
            i += 1
    else:
        s, e, span = find_range(header)
        if span is not None:
            start, end = s, e
            header = _strip_span(header, span)
    lead: list[str] = []
    if extras:  # "Pune, India Example Institute of ..." : the place, then wrapped details
        place, tail = _split_location(extras[0])
        if tail and place:
            extras[0] = place
            lead.append(tail)
        elif tail and len(extras[0]) > 60:
            lead.append(extras.pop(0))
    body = _items(lines[i:])
    # Plain lines right after the date line (PDF-wrapped details) are part of the lead text.
    while body and not body[0].bullet:
        lead.append(clean(body.pop(0).text))
    return _Header(_clean_item(header), start, end, extras, body, lead)


def _description(h: _Header, *, skip_tech: bool = False) -> str | None:
    parts = list(h.lead)
    for it in h.body:
        text = _clean_item(it.text)
        if skip_tech and _TECH_LINE.match(text):
            continue
        parts.append(text)
    out = "\n".join(p for p in parts if p)
    return out[:5000] or None


def _excerpt(text: str, start: int, end: int) -> str:
    return text[start:end][:1000]


def _validated(section: Section, data: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return validate_fact_data(section, data)
    except ValidationFailed:
        return None


def _fallback(full: str, entry: _Entry, reason: str) -> ExtractedFact:
    start, end = entry.lines[0].start, entry.lines[-1].end
    first = _clean_item(entry.lines[0].text)[:500] or "Untitled entry"
    rest = "\n".join(_clean_item(ln.text) for ln in entry.lines[1:] if ln.text.strip())
    data = {"title": first, "description": rest[:5000] or None}
    return ExtractedFact(
        Section.OTHER,
        validate_fact_data(Section.OTHER, data),
        start,
        end,
        _excerpt(full, start, end),
        [reason],
        "low",
    )


def _span(entry: _Entry) -> tuple[int, int]:
    return entry.lines[0].start, entry.lines[-1].end


def _split_parts(header: str) -> list[str]:
    return [p.strip() for p in _SEPARATORS.split(header) if p and p.strip()]


@lru_cache(maxsize=1)
def _country_names() -> re.Pattern[str]:
    from nexscout.domain.geo import countries

    names = sorted((c.name for c in countries().values()), key=len, reverse=True)
    return re.compile(r",\s*(?:" + "|".join(re.escape(n) for n in names) + r")\b")


def _split_location(text: str) -> tuple[str | None, str | None]:
    """("Pune, India Example School of Computing." -> "Pune, India", "Example School ...")."""
    m = _country_names().search(text)
    if m:
        rest = text[m.end() :].strip(" .,;")
        return text[: m.end()].strip(), rest or None
    if len(text) <= 40 and not _URL.search(text) and ". " not in text:
        return text.strip(), None
    return None, text


def _location(extras: list[str]) -> str | None:
    if extras and not _URL.search(extras[0]):
        return _split_location(extras[0])[0]
    return None


# ------------------------------------------------------------------------------- entries
def _employment(full: str, entry: _Entry) -> ExtractedFact:
    h = _parse_header(entry)
    warnings: list[str] = []
    title = org = None
    dash = _DASH_SPLIT.split(h.text, maxsplit=1) if _DASH_SPLIT.search(h.text) else []
    if len(dash) == 2:
        title, org = dash[0].strip(), dash[1].strip()
    else:
        parts = _split_parts(h.text) + [x for x in h.extras[1:2] if not _location([x])]
        if len(parts) >= 2:
            a, b = parts[0], parts[1]
            if _TITLE_WORDS.search(b) and not _TITLE_WORDS.search(a):
                title, org = b, a
            else:
                title, org = a, b
                if not _TITLE_WORDS.search(a):
                    warnings.append(
                        "Check which part is the job title and which is the organization."
                    )
    if title and org and _TITLE_WORDS.search(org) and not _TITLE_WORDS.search(title):
        title, org = org, title
    if not title or not org:
        return _fallback(full, entry, "Couldn't tell the job title and organization apart.")
    data = _validated(
        Section.EMPLOYMENT,
        {
            "title": title[:500],
            "organization": org[:500],
            "location": _location(h.extras),
            "start": h.start,
            "end": h.end,
            "description": _description(h),
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = _span(entry)
    return ExtractedFact(
        Section.EMPLOYMENT,
        data,
        s,
        e,
        _excerpt(full, s, e),
        warnings,
        "low" if warnings else "medium",
    )


def _education(full: str, entry: _Entry) -> ExtractedFact:
    h = _parse_header(entry)
    parts = _split_parts(h.text)
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
            if degree.lower() in {
                "master",
                "masters",
                "master's",
                "bachelor",
                "bachelors",
                "bachelor's",
                "doctor",
            }:
                degree = degree_part  # "Master of Computer Applications (MCA)" stays whole
                field_of_study = None  # already in the degree's name
        else:
            degree = degree_part
    data = _validated(
        Section.EDUCATION,
        {
            "institution": institution[:500],
            "degree": degree,
            "field_of_study": field_of_study,
            "location": _location(h.extras),
            "start": h.start,
            "end": h.end,
            "description": _description(h),
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = _span(entry)
    return ExtractedFact(
        Section.EDUCATION,
        data,
        s,
        e,
        _excerpt(full, s, e),
        warnings,
        "low" if warnings else "medium",
    )


def _role_at_org(full: str, entry: _Entry, section: Section) -> ExtractedFact:
    h = _parse_header(entry)
    parts = _split_parts(h.text) + h.extras[1:2]
    if not parts:
        return _fallback(full, entry, "Couldn't read this entry.")
    role, org = (parts[0], parts[1]) if len(parts) >= 2 else (None, parts[0])
    if section is Section.RESEARCH:
        payload: dict[str, Any] = {
            "title": h.text[:500] or parts[0][:500],
            "organization": h.extras[0][:500] if h.extras else None,
            "start": h.start,
            "end": h.end,
            "description": _description(h),
        }
    else:
        payload = {
            "organization": org[:500],
            "role": role[:500] if role else None,
            "start": h.start,
            "end": h.end,
            "description": _description(h),
        }
    data = _validated(section, payload)
    if data is None:
        return _fallback(full, entry, "Couldn't read this entry's structure.")
    s, e = _span(entry)
    return ExtractedFact(section, data, s, e, _excerpt(full, s, e))


def _url_in(texts: list[str]) -> str | None:
    joined = " ".join(texts)
    if m := _URL.search(joined):
        return m.group(0).rstrip(".,;*")
    if m := _BARE_URL.search(joined):
        return "https://" + m.group(0).rstrip(".,;*").removeprefix("https://")
    return None


def _project(full: str, entry: _Entry) -> ExtractedFact:
    h = _parse_header(entry)
    name, tagline = h.text, None
    if _DASH_SPLIT.search(h.text):
        name, tagline = (p.strip() for p in _DASH_SPLIT.split(h.text, maxsplit=1))
    tech: list[str] = []
    for it in h.body:
        t = _clean_item(it.text)
        if _TECH_LINE.match(t):
            tech = [x for x in _top_level_split(_TECH_LINE.sub("", t)) if _plausible_skill(x)]
    org_hint = next(
        (
            x
            for x in h.extras
            if not _URL.search(x)
            and not _BARE_URL.search(x)
            and not _DOMAIN.fullmatch(x)
            and x.lower() not in {"independent", "personal", "freelance", "open source"}
        ),
        None,
    )
    desc = _description(h, skip_tech=True)
    if tagline:
        desc = f"{tagline}\n{desc}" if desc else tagline
    data = _validated(
        Section.PROJECT,
        {
            "name": (name or (h.extras[0] if h.extras else ""))[:500],
            "start": h.start,
            "end": h.end,
            "description": desc,
            "url": _url_in(h.extras)
            or _url_in([ln.text for ln in entry.lines])
            or next(("https://" + x for x in h.extras if _DOMAIN.fullmatch(x)), None),
            "technologies": tech[:50],
        },
    )
    if data is None:
        return _fallback(full, entry, "Couldn't read this project entry.")
    s, e = _span(entry)
    return ExtractedFact(Section.PROJECT, data, s, e, _excerpt(full, s, e), org_hint=org_hint)


# ----------------------------------------------------------------------------- skills
def _top_level_split(text: str) -> list[str]:
    """Split at , ; | • · only outside parentheses."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if depth == 0 and ch in ",;|•·":
            out.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    out.append("".join(buf).strip())
    return [x.strip().strip(".") for x in out if x.strip().strip(".")]


def _expand_skill(item: str) -> list[str]:
    """ "JavaScript (React.js, Angular)" -> JavaScript, React.js, Angular. An acronym in brackets
    stays with its name ("Retrieval-Augmented Generation (RAG)"). A slash splits only between
    single tokens ("llama.cpp/GGUF", not "LoRA/QLoRA Fine-Tuning")."""
    m = re.fullmatch(r"(?P<head>[^()]+?)\s*\((?P<inner>[^()]+)\)", item)
    names: list[str] = []
    if m:
        head, inner = m.group("head").strip(), m.group("inner").strip()
        initials = "".join(w[0] for w in re.split(r"[\s-]+", head) if w).upper()
        if re.fullmatch(r"[A-Z0-9]{2,8}", inner) and initials.startswith(inner[:2]):
            return [item]  # an acronym of the name
        names.append(head)
        names.extend(_top_level_split(inner))
    else:
        names.append(item)
    out: list[str] = []
    for n in names:
        if re.fullmatch(r"[\w.+#-]+(?:/[\w.+#-]+)+", n):
            out.extend(p for p in n.split("/") if p)
        else:
            out.append(n)
    return out


def _plausible_skill(name: str) -> bool:
    n = name.strip()
    if not n or len(n) > 60 or len(n.split()) > 6:
        return False
    if len(n) == 1 and not n.isupper():
        return False
    if n.count("(") != n.count(")") or n[0] in ".,;:)-/&" or n[-1] in ",;:(/&":
        return False
    return any(c.isalnum() for c in n)


def is_plausible_skill(name: str) -> bool:
    """A short skill name, not a sentence or a fragment (also checks AI-proposed skills)."""
    return _plausible_skill(name)


def _skills(full: str, block: Block) -> list[ExtractedFact]:
    out: list[ExtractedFact] = []
    seen: set[str] = set()
    for it in _items(block.lines):
        raw = _clean_item(it.text)
        if not raw:
            continue
        category = None
        if ":" in raw and raw.index(":") < 40:
            category, raw = (x.strip() for x in raw.split(":", 1))
        if block.spoken_languages:
            names, level = [category or raw], (raw if category else None)
            category = SPOKEN_CATEGORY
            if level:
                level = re.split(r"(?<=[a-z)])\.\s", level)[0][:80]
        else:
            names = [n for item in _top_level_split(raw) for n in _expand_skill(item)]
            level = None
        for name in names:
            name = name.strip().strip(".")
            if not _plausible_skill(name) or name.lower() in seen:
                continue
            seen.add(name.lower())
            data = _validated(
                Section.SKILL, {"name": name, "category": category or None, "level": level}
            )
            if data:
                out.append(
                    ExtractedFact(
                        Section.SKILL, data, it.start, it.end, _excerpt(full, it.start, it.end)
                    )
                )
    return out


@dataclass(frozen=True)
class _Citation:
    authors: str
    title: str
    venue: str | None
    tail: str  # everything after the title: venue, pages, publisher, year, DOI


def _citation(raw: str) -> _Citation | None:
    """Split "A. Author, B. Author. Title. In Venue, pp. 1-9. Press, 2025." into its parts.
    The author list ends at the first full stop after a surname (not after an initial)."""
    cut = None
    for m in re.finditer(r"\.\s+", raw):
        token = raw[: m.start()].rsplit(None, 1)[-1].strip(",") if raw[: m.start()].strip() else ""
        if token and not re.fullmatch(r"[A-Z](?:\.-?[A-Z])*", token):
            cut = m
            break
    if cut is None:
        return None
    authors = raw[: cut.start()].strip()
    if not authors[:1].isupper() or len(authors) > 400 or re.search(r"\d", authors):
        return None
    if not re.search(r"\b[A-Z]\.", authors):  # cited names carry initials ("R. Example")
        return None
    rest = raw[cut.end() :]
    end = re.search(r"(?<=[.?!])\s+", rest)
    title = (rest[: end.start()] if end else rest).strip().rstrip(".")
    if len(title) < 3:
        return None
    venue = None
    tail = rest[end.end() :] if end else ""
    if lead := re.match(r"In:?\s+", tail):
        body = tail[lead.end() :]
        stop = len(body)
        for c in re.finditer(r",\s*pp?\.|,\s*\d{4}|\.\s", body):
            word = body[: c.start()].rsplit(None, 1)[-1] if body[: c.start()].strip() else ""
            if c.group(0)[0] == "." and len(word) <= 4 and word[:1].isupper():
                continue  # an abbreviation inside the venue: "Proc.", "Int.", "Vol."
            stop = c.start()
            break
        venue = body[:stop].strip().rstrip(".,") or None
    return _Citation(authors, title, venue, tail)


def _simple_items(full: str, block: Block) -> list[ExtractedFact]:
    out: list[ExtractedFact] = []
    items = _items(block.lines)
    if any(it.bullet for it in items):  # a lead-in line ("Google Scholar: 10 citations") isn't one
        items = [it for it in items if it.bullet]
    for it in items:
        raw = _clean_item(it.text)
        if not raw:
            continue
        section = block.section
        payload: dict[str, Any]
        org_hint = None
        if section is Section.PUBLICATION:
            doi = _DOI.search(raw)
            url = _URL.search(raw)
            cite = _citation(raw)
            year = _YEAR.search(_DOI.sub("", cite.tail if cite else "")) or _YEAR.search(
                _DOI.sub("", raw)
            )
            payload = {
                "title": (cite.title if cite else raw)[:500],
                "authors": cite.authors[:500] if cite else None,
                "venue": cite.venue[:500] if cite and cite.venue else None,
                "year": year.group(0) if year else None,
                "doi": doi.group(0).rstrip(".") if doi else None,
                "url": url.group(0) if url else None,
            }
        elif section in (Section.CERTIFICATION, Section.AWARD):
            m = _SINGLE_DATE.search(raw)
            date = to_partial_date(m.group(0)) if m else None
            name = _strip_span(raw, m.span()) if m else raw
            issuer = None
            dash = _DASH_SPLIT.split(name, maxsplit=1) if " -- " in name or " — " in name else []
            if len(dash) == 2 and len(dash[1]) <= 120:
                name, issuer = dash[0].strip(), dash[1].strip()
                org_hint = issuer
            payload = {"name": (name or raw)[:500], "date": date, "issuer": issuer}
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
                    section,
                    data,
                    it.start,
                    it.end,
                    _excerpt(full, it.start, it.end),
                    org_hint=org_hint if section is not Section.CERTIFICATION else None,
                )
            )
    return out


# ------------------------------------------------------------------------------- links
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _link(facts: list[ExtractedFact]) -> None:
    """A project done in a job or a degree: its date line names the employer or university,
    or the job's description names the project. Pending like everything else, so the user
    confirms the link."""
    places = [
        (i, f, str(f.data.get("organization") or f.data.get("institution") or ""))
        for i, f in enumerate(facts)
        if f.section in (Section.EMPLOYMENT, Section.EDUCATION)
    ]
    for f in facts:
        if f.section is not Section.PROJECT:
            continue
        name = _norm(str(f.data.get("name", "")))
        hint = _norm(f.org_hint or "")
        matches = []
        for i, place, org_name in places:
            org = _norm(org_name)
            desc = _norm(str(place.data.get("description", "")))
            if (hint and org and (hint == org or hint in org or org in hint)) or (
                place.section is Section.EMPLOYMENT
                and len(name) >= 4
                and f" {name} " in f" {desc} "
            ):
                matches.append((i, place))
        # Two degrees at one university: the one whose dates hold the project's start.
        when = str(f.data.get("start") or "")
        during = [
            i
            for i, p in matches
            if when
            and str(p.data.get("start") or "") <= when
            and (
                str(p.data.get("end") or "present") in ("present", "") or when <= str(p.data["end"])
            )
        ]
        if during or matches:
            f.related.append((during or [matches[0][0]])[0])


def extract_facts(text: str) -> list[ExtractedFact]:
    """Run the full heuristic pipeline over normalized document text."""
    facts: list[ExtractedFact] = []
    for block in split_sections(text):
        section = block.section
        if section is Section.SUMMARY:
            body = clean(" ".join(ln.text.strip() for ln in block.lines))
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
    _link(facts)
    return facts
