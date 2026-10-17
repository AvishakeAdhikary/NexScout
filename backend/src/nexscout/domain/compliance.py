"""Does a rendered document meet the posting's requirements and the regional conventions?

Two sources, two severities:
- **posting** requirements found by research (e.g. "Research statement (max. 2 pages)") are
  *blocking*: an application that breaks them risks rejection, so NexScout won't upload it.
- **convention** limits from the regional format (domain/formats.py) are *warnings*.
Unfilled placeholders are always blocking: the document isn't finished.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from nexscout.domain.drafting import PLACEHOLDER, DocType, find_placeholders

# Which research finding fields describe which document.
DOC_FIELDS: dict[DocType, tuple[str, ...]] = {
    DocType.RESUME: ("cv",),
    DocType.ACADEMIC_CV: ("cv",),
    DocType.SOP: ("statement",),
    DocType.COVER_LETTER: ("statement",),
    DocType.RESEARCH_PROPOSAL: ("proposal",),
}
# Words that identify which "statement" a requirement is about.
_STATEMENT_HINTS: dict[DocType, re.Pattern[str]] = {
    DocType.SOP: re.compile(r"statement|purpose|motivation|personal", re.I),
    DocType.COVER_LETTER: re.compile(r"cover|motivation letter|letter of motivation", re.I),
}
_PAGES = re.compile(
    r"(?:max(?:imum)?\.?|at most|up to|no more than|not exceed(?:ing)?)\s*(?:of\s*)?(\d{1,2})"
    r"\s*(?:A4\s*)?pages?|(\d{1,2})[\s-]*page(?:s)?\s*(?:max(?:imum)?|limit)",
    re.I,
)
_WORDS = re.compile(
    r"(?:max(?:imum)?\.?|at most|up to|no more than|not exceed(?:ing)?)\s*(?:of\s*)?"
    r"(\d{2,5})\s*words|(\d{2,5})[\s-]*words?\s*(?:max(?:imum)?|limit)",
    re.I,
)


@dataclass(frozen=True)
class Check:
    rule: str
    ok: bool
    severity: str  # blocking | warning | info
    source: str  # "posting: <quote>" | "convention: <format>" | "document"
    detail: str


def _limit(pattern: re.Pattern[str], text: str) -> int | None:
    m = pattern.search(text)
    if not m:
        return None
    return int(next(g for g in m.groups() if g))


def word_count(markdown: str) -> int:
    text = PLACEHOLDER.sub(" ", markdown)
    text = re.sub(r"[#*_`>|-]", " ", text)
    return len(re.findall(r"[\w'\u2019]+", text))


def posting_requirements(doc_type: DocType, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Research findings that state a length limit for this kind of document."""
    fields = DOC_FIELDS.get(doc_type, ())
    hint = _STATEMENT_HINTS.get(doc_type)
    out = []
    for f in findings:
        if f.get("kind") != "document_required" or f.get("field") not in fields:
            continue
        quote = str(f.get("quote") or f.get("summary") or "")
        if f.get("field") == "statement" and hint is not None and not hint.search(quote):
            continue
        pages, words = _limit(_PAGES, quote), _limit(_WORDS, quote)
        if pages or words:
            out.append({"quote": quote, "pages": pages, "words": words})
    return out


def check_document(
    doc_type: DocType,
    markdown: str,
    pdf_pages: int | None,
    fmt: dict[str, Any],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    checks: list[Check] = []
    placeholders = find_placeholders(markdown)
    checks.append(
        Check(
            "No placeholders left",
            not placeholders,
            "blocking",
            "document",
            "Complete."
            if not placeholders
            else f"{len(placeholders)} to fill: " + "; ".join(placeholders[:5]),
        )
    )
    words = word_count(markdown)
    for req in posting_requirements(doc_type, findings):
        src = f"posting: {req['quote'][:160]}"
        if req["pages"] and pdf_pages is not None:
            checks.append(
                Check(
                    f"At most {req['pages']} page(s), as the posting asks",
                    pdf_pages <= req["pages"],
                    "blocking",
                    src,
                    f"The PDF has {pdf_pages} page(s).",
                )
            )
        if req["words"]:
            checks.append(
                Check(
                    f"At most {req['words']} words, as the posting asks",
                    words <= req["words"],
                    "blocking",
                    src,
                    f"The document has about {words} words.",
                )
            )
    limit = (fmt.get("page_limits") or {}).get(doc_type.value)
    if limit and pdf_pages is not None:
        checks.append(
            Check(
                f"Usually at most {limit} page(s) in this format",
                pdf_pages <= limit,
                "warning",
                f"convention: {fmt.get('label')}",
                f"The PDF has {pdf_pages} page(s).",
            )
        )
    checks.append(
        Check(
            f"{fmt.get('paper', 'A4')} paper",
            True,
            "info",
            f"convention: {fmt.get('label')}",
            "Rendered in the format's paper size.",
        )
    )
    blocking = [c for c in checks if not c.ok and c.severity == "blocking"]
    warnings = [c for c in checks if not c.ok and c.severity == "warning"]
    return {
        "status": "blocking" if blocking else "warnings" if warnings else "ok",
        "checks": [asdict(c) for c in checks],
        "words": words,
        "pages": pdf_pages,
    }
