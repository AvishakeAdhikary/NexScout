"""Rule-based extraction of application requirements from source text (`rules_v1`).

Pure functions: text in, findings out. Every finding carries a `quote` that is an exact substring
of the source text, so a reader can always check it against the page. The rules are deliberately
conservative: they miss things rather than invent them, and confidence says how direct the
evidence is. Nothing here calls a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

METHOD = "rules_v1"
STALE_AFTER = timedelta(days=30)


class FindingKind(StrEnum):
    DEADLINE = "deadline"
    DEGREE = "degree"
    LANGUAGE_TEST = "language_test"
    DOCUMENT_REQUIRED = "document_required"
    FUNDING = "funding"
    SUPERVISOR = "supervisor"
    OTHER = "other"


@dataclass
class Finding:
    kind: FindingKind
    field: str
    summary: str
    quote: str
    value: dict[str, Any] = dc_field(default_factory=dict)
    confidence: str = "medium"


_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_PATTERNS = [
    re.compile(r"\b(?P<y>20\d\d)-(?P<m>0[1-9]|1[0-2])-(?P<d>0[1-9]|[12]\d|3[01])\b"),
    re.compile(
        rf"\b(?P<d>[0-3]?\d)(?:st|nd|rd|th)?\.?\s+(?P<mon>{_MONTH_RE})\.?,?\s+(?P<y>20\d\d)\b", re.I
    ),
    re.compile(
        rf"\b(?P<mon>{_MONTH_RE})\.?\s+(?P<d>[0-3]?\d)(?:st|nd|rd|th)?,?\s+(?P<y>20\d\d)\b", re.I
    ),
    re.compile(r"\b(?P<d>[0-3]?\d)\.(?P<m>[01]?\d)\.(?P<y>20\d\d)\b"),
]
_DEADLINE_CUE = re.compile(
    r"\b(deadline|apply by|applications? (?:are |will be )?(?:close|due)|closing date|closes on|"
    r"submit (?:your application|applications) by|no later than)\b",
    re.I,
)
_IELTS = re.compile(r"\bIELTS\b[^.\n]{0,60}?\b([4-9](?:\.[05])?)\b")
_TOEFL = re.compile(r"\bTOEFL(?:\s*iBT)?\b[^.\n]{0,60}?\b(\d{2,3})\b")
_DEGREE = re.compile(
    r"\b(master'?s|M\.?\s?Sc\.?|M\.?\s?A\.?|bachelor'?s|B\.?\s?Sc\.?|diploma|doctoral|PhD)\b"
    r"[^.\n]{0,40}\b(degree|qualification)\b",
    re.I,
)
_DEGREE_CUE = re.compile(
    r"\b(required|must|should|hold|completed|expected|candidates? with)\b", re.I
)
_FUNDING = re.compile(
    r"\b(fully funded|funded|stipend|salary|TV-L|scholarship|studentship|tuition|fees? waiver)\b",
    re.I,
)
_DOCS_CUE = re.compile(
    r"\b(required documents|application documents|please (?:submit|include|send)|"
    r"your application should (?:include|contain)|applications? must include|"
    r"to apply,? (?:send|submit))\b",
    re.I,
)
_DOC_TYPES = [
    ("cv", re.compile(r"\b(CV|curriculum vitae|r[ée]sum[ée])\b", re.I)),
    (
        "transcript",
        re.compile(r"\btranscripts?\b|\bgrades?\b|\bdiploma (?:supplement|certificate)", re.I),
    ),
    (
        "reference_letter",
        re.compile(
            r"\b(reference|recommendation) letters?\b|\breferees?\b"
            r"|\bletters? of (?:reference|recommendation)\b",
            re.I,
        ),
    ),
    (
        "statement",
        re.compile(
            r"\b(statement|letter) of (?:purpose|motivation|interest)\b"
            r"|\b(motivation|cover) letter\b|\b(research|personal) statement\b",
            re.I,
        ),
    ),
    ("proposal", re.compile(r"\b(research )?proposal\b|\bresearch plan\b", re.I)),
    (
        "language_certificate",
        re.compile(r"\b(IELTS|TOEFL|language certificate|proof of English)\b", re.I),
    ),
    ("writing_sample", re.compile(r"\bwriting sample\b|\b(thesis|publications?)\b", re.I)),
]
_PERSON = re.compile(
    r"\b(?P<title>Prof\.(?:\s*Dr\.)?|Professor|Dr\.|Assoc\.\s*Prof\.)\s+"
    r"(?P<name>[A-ZÀ-Ý][\w'\u2019\-]+(?:\s+[A-ZÀ-Ý][\w'\u2019\-]+){0,3})"
)
_SUPERVISOR_CUE = re.compile(
    r"\b(supervis\w*|group lead\w*|principal investigator|PI\b|head of|contact|"
    r"research interests|lab|group|chair)\b",
    re.I,
)
_INTERESTS = re.compile(r"research interests?\s*(?:include|are|:)\s*(?P<list>[^.\n]+)", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")
# Abbreviations that end with a period but don't end a sentence.
_ABBREV = re.compile(
    r"(?:\b(?:Prof|Dr|Assoc|Mr|Ms|Mrs|St|No|approx|max|min|incl|e\.g|i\.e|cf|vs|etc)\.)$", re.I
)


def parse_date(text: str) -> date | None:
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        g = m.groupdict()
        try:
            month = int(g["m"]) if g.get("m") else _MONTHS[g["mon"].lower().rstrip(".")]
            return date(int(g["y"]), month, int(g["d"]))
        except (ValueError, KeyError):
            continue
    return None


def sentences(text: str) -> list[str]:
    """Lines, then sentences within lines. Each result is an exact substring of `text`."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        body = line[2:] if line.startswith("- ") else line
        parts: list[str] = []
        pos = 0
        for m in _SENTENCE_END.finditer(body):
            if _ABBREV.search(body[pos : m.start()]):
                continue  # "Prof. Dr. Jana ..." is one sentence
            parts.append(body[pos : m.start()])
            pos = m.end()
        parts.append(body[pos:])
        out.extend(p.strip() for p in parts if p.strip())
    return out


def _doc_field(item: str) -> str:
    for name, pat in _DOC_TYPES:
        if pat.search(item):
            return name
    return "other"


def _documents(text: str) -> list[Finding]:
    """Bullet items (and comma lists) that follow a 'required documents' cue."""
    found: list[Finding] = []
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if not _DOCS_CUE.search(line):
            continue
        items: list[str] = []
        j = i + 1
        while j < len(lines) and (lines[j].startswith("- ") or not lines[j]):
            if lines[j]:
                items.append(lines[j][2:].strip())
            elif items and not any(ln.startswith("- ") for ln in lines[j + 1 : j + 2]):
                break  # a blank line that doesn't continue the list ends it
            j += 1
        if not items and ":" in line:  # "Please submit: a CV, transcripts and two letters."
            tail = line.split(":", 1)[1]
            items = [p.strip(" .;") for p in re.split(r",|;|\band\b", tail) if p.strip(" .;")]
        for item in items[:20]:
            if item and item in text:
                found.append(
                    Finding(
                        FindingKind.DOCUMENT_REQUIRED,
                        _doc_field(item),
                        f"Submit: {item}",
                        item,
                        {"item": item},
                        "high",
                    )
                )
    return found


def _supervisors(text: str, links: list[tuple[str, str]]) -> list[Finding]:
    found: dict[str, Finding] = {}
    for sent in sentences(text):
        if not _SUPERVISOR_CUE.search(sent):
            continue
        for m in _PERSON.finditer(sent):
            name = m.group("name").strip()
            if name in found:
                continue
            interests = _INTERESTS.search(sent)
            areas = (
                [
                    a.strip(" .")
                    for a in re.split(r",|;|\band\b", interests.group("list"))
                    if a.strip(" .")
                ]
                if interests
                else []
            )
            href = next((u for t, u in links if name in t), None)
            found[name] = Finding(
                FindingKind.SUPERVISOR,
                "person",
                f"{m.group('title')} {name}",
                sent,
                {
                    "name": name,
                    "title": m.group("title"),
                    "research_interests": areas[:10],
                    "profile_url": href,
                },
                "medium"
                if not re.search(r"supervis|principal investigator|PI\b", sent, re.I)
                else "high",
            )
    return list(found.values())


def extract_findings(text: str, links: list[tuple[str, str]] | None = None) -> list[Finding]:
    """All rule-based findings in `text` (deduplicated by kind/field/quote)."""
    findings: list[Finding] = []
    for sent in sentences(text):
        if _DEADLINE_CUE.search(sent) and (d := parse_date(sent)):
            findings.append(
                Finding(
                    FindingKind.DEADLINE,
                    "application",
                    f"Application deadline: {d.day} {d:%B %Y}",
                    sent,
                    {"date": d.isoformat()},
                    "high",
                )
            )
        for pat, test in ((_IELTS, "IELTS"), (_TOEFL, "TOEFL")):
            if m := pat.search(sent):
                score = float(m.group(1)) if test == "IELTS" else int(m.group(1))
                findings.append(
                    Finding(
                        FindingKind.LANGUAGE_TEST,
                        test.lower(),
                        f"{test} minimum: {m.group(1)}",
                        sent,
                        {"test": test, "min_score": score},
                        "high",
                    )
                )
        if _DEGREE.search(sent) and _DEGREE_CUE.search(sent):
            findings.append(
                Finding(FindingKind.DEGREE, "required_degree", sent[:200], sent, {}, "medium")
            )
        if _FUNDING.search(sent):
            findings.append(Finding(FindingKind.FUNDING, "funding", sent[:200], sent, {}, "medium"))
    findings.extend(_documents(text))
    findings.extend(_supervisors(text, links or []))
    seen: set[tuple[str, str, str]] = set()
    unique: list[Finding] = []
    for f in findings:
        key = (f.kind.value, f.field, f.quote)
        if key not in seen and f.quote in text:  # quotes are always verbatim
            seen.add(key)
            unique.append(f)
    return unique


def conflicts(findings: list[tuple[str, Finding]]) -> dict[int, str]:
    """Indexes of findings that disagree across sources, with a note. Input: (source, finding)."""
    notes: dict[int, str] = {}
    groups: dict[tuple[str, str], list[int]] = {}
    for i, (_, f) in enumerate(findings):
        if f.kind in (FindingKind.DEADLINE, FindingKind.LANGUAGE_TEST):
            groups.setdefault((f.kind.value, f.field), []).append(i)
    for (kind, _), idxs in groups.items():
        key = "date" if kind == FindingKind.DEADLINE.value else "min_score"
        values = {str(findings[i][1].value.get(key)) for i in idxs}
        sources = {findings[i][0] for i in idxs}
        if len(values) > 1 and len(sources) > 1:
            note = f"Sources disagree: {', '.join(sorted(values))}. Check the official page."
            for i in idxs:
                notes[i] = note
    return notes


def is_stale(retrieved_at: datetime, now: datetime) -> bool:
    return now - retrieved_at > STALE_AFTER
