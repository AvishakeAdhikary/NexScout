"""Truthful application documents: types, the drafting contract, and the deterministic verifier.

A model *proposes* a draft as typed sentences that cite their support. This module *disposes*:
- `claim` sentences (about the candidate) must cite accepted profile entries, and every number
  in them must appear in those entries;
- `position` sentences (about the opportunity) must be supported by research findings or the
  listing, numbers included;
- `intent` sentences (motivation, plans) carry no facts and no numbers, and are flagged for the
  user to confirm in their own words;
- anything missing becomes `[[PLACEHOLDER: …]]`, never an invented fact.
Unsupported sentences are removed and reported, so the user sees exactly what was dropped and why.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nexscout.domain.profile import Section, fact_label

PLACEHOLDER = re.compile(r"\[\[PLACEHOLDER:\s*([^\]]{1,300}?)\s*\]\]")
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")


class DocType(StrEnum):
    SOP = "sop"
    RESEARCH_PROPOSAL = "research_proposal"
    ACADEMIC_CV = "academic_cv"
    INQUIRY_EMAIL = "inquiry_email"
    RESUME = "resume"
    COVER_LETTER = "cover_letter"
    REFERRAL_REQUEST = "referral_request"


@dataclass(frozen=True)
class DocSpec:
    label: str
    sections: tuple[str, ...]
    headings: bool = True  # emails and letters are rendered without section headings
    needs_opportunity: bool = True
    uses_model: bool = True


DOC_SPECS: dict[DocType, DocSpec] = {
    DocType.SOP: DocSpec(
        "Statement of purpose",
        (
            "Motivation",
            "Academic background",
            "Research experience",
            "Fit with the position",
            "Goals",
        ),
    ),
    DocType.RESEARCH_PROPOSAL: DocSpec(
        "Research proposal",
        ("Background", "Research questions", "Approach", "Relevant preparation", "Timeline"),
    ),
    DocType.ACADEMIC_CV: DocSpec("Academic CV", (), needs_opportunity=False, uses_model=False),
    DocType.INQUIRY_EMAIL: DocSpec(
        "Inquiry email to a potential supervisor",
        ("Greeting", "Introduction", "Fit", "Request", "Closing"),
        headings=False,
    ),
}
DOC_SPECS.update(
    {
        DocType.RESUME: DocSpec("Resume", (), needs_opportunity=False, uses_model=False),
        DocType.COVER_LETTER: DocSpec(
            "Cover letter",
            ("Greeting", "Opening", "Relevant experience", "Fit with the role", "Closing"),
            headings=False,
        ),
        DocType.REFERRAL_REQUEST: DocSpec(
            "Referral request",
            ("Greeting", "Context", "Request", "Closing"),
            headings=False,
        ),
    }
)
PHD_DOC_TYPES = (DocType.SOP, DocType.RESEARCH_PROPOSAL, DocType.ACADEMIC_CV, DocType.INQUIRY_EMAIL)
JOB_DOC_TYPES = (DocType.RESUME, DocType.COVER_LETTER, DocType.REFERRAL_REQUEST)
AVAILABLE_DOC_TYPES = PHD_DOC_TYPES + JOB_DOC_TYPES


# --- What a model returns (validated with Pydantic, JSON schema for structured output) --------


class DraftSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=800)
    kind: Literal["claim", "position", "intent", "placeholder"]
    fact_ids: list[str] = Field(max_length=12)
    finding_ids: list[str] = Field(max_length=12)
    new_paragraph: bool


class DraftSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str = Field(max_length=120)
    sentences: list[DraftSentence] = Field(max_length=40)


class DraftDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=200)
    sections: list[DraftSection] = Field(max_length=12)


# --- Verifier -------------------------------------------------------------------------------


@dataclass
class VerifiedDraft:
    markdown: str
    report: dict[str, Any]
    placeholders: list[str] = field(default_factory=list)


def placeholder(text: str) -> str:
    return f"[[PLACEHOLDER: {text}]]"


def find_placeholders(markdown: str) -> list[str]:
    return [m.group(1).strip() for m in PLACEHOLDER.finditer(markdown)]


def _norm(n: str) -> str:
    n = n.replace(",", ".")
    return n.lstrip("0") or "0" if "." not in n else n


def _numbers(text: str) -> list[str]:
    """Numbers outside placeholders, normalized ("01" == "1"), as whole tokens."""
    return [_norm(n) for n in _NUMBER.findall(PLACEHOLDER.sub(" ", text))]


def _number_set(text: str) -> set[str]:
    return {_norm(n) for n in _NUMBER.findall(text)}


def _clean(text: str) -> str:
    return " ".join(text.split())


def verify_draft(
    draft: DraftDocument,
    doc_type: DocType,
    facts: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
    listing_text: str,
) -> VerifiedDraft:
    """Keep only supported sentences; report everything. Deterministic and side-effect free."""
    spec = DOC_SPECS[doc_type]
    report: dict[str, Any] = {
        "claims": [],
        "position": [],
        "to_check": [],
        "removed": [],
        "missing_sections": [],
    }
    kept_sections: dict[str, list[list[str]]] = {}
    for section in draft.sections:
        heading = _clean(section.heading) or "Untitled"
        paragraphs = kept_sections.setdefault(heading, [])
        for s in section.sentences:
            text = _clean(s.text)
            if not text:
                continue
            reason: str | None = None
            nums = _numbers(text)
            if s.kind == "placeholder":
                if not PLACEHOLDER.search(text):
                    text = placeholder(text[:200])
            elif s.kind == "claim":
                ids = [i for i in s.fact_ids if isinstance(i, str)]
                if not ids:
                    reason = "states something about you without citing a profile entry"
                elif any(i not in facts for i in ids):
                    reason = "cites profile entries that don't exist or aren't confirmed"
                else:
                    source = _number_set(json.dumps([facts[i] for i in ids], ensure_ascii=False))
                    missing = [n for n in nums if n not in source]
                    if missing:
                        reason = f"numbers not in the cited entries: {', '.join(missing)}"
                if reason is None:
                    report["claims"].append({"text": text, "fact_ids": ids})
            elif s.kind == "position":
                ids = [i for i in s.finding_ids if isinstance(i, str)]
                if any(i not in findings for i in ids):
                    reason = "cites research findings that don't exist"
                else:
                    source = _number_set(
                        listing_text + json.dumps([findings[i] for i in ids], ensure_ascii=False)
                    )
                    missing = [n for n in nums if n not in source]
                    if missing:
                        reason = (
                            f"numbers not found in the listing or research: {', '.join(missing)}"
                        )
                if reason is None:
                    report["position"].append({"text": text, "finding_ids": ids})
            else:  # intent
                if nums:
                    reason = "a statement of intent can't contain facts or figures"
                else:
                    report["to_check"].append(
                        {"text": text, "reason": "Written for you. Keep it only if it's true."}
                    )
            if reason:
                report["removed"].append({"text": text, "kind": s.kind, "reason": reason})
                continue
            if s.new_paragraph or not paragraphs:
                paragraphs.append([])
            paragraphs[-1].append(text)

    for required in spec.sections:
        if not any(p for p in kept_sections.get(required, [])):
            report["missing_sections"].append(required)
            kept_sections[required] = [[placeholder(f"{required}: add this in your own words")]]
    ordered = [h for h in spec.sections if h in kept_sections] + [
        h for h in kept_sections if h not in spec.sections and kept_sections[h]
    ]

    title = _clean(draft.title) or spec.label
    lines: list[str] = []
    if spec.headings:
        lines += [f"# {title}", ""]
        for h in ordered:
            lines += [f"## {h}", ""]
            for p in kept_sections[h]:
                if p:
                    lines += [" ".join(p), ""]
    else:
        lines += [f"Subject: {title}", ""]
        for h in ordered:
            for p in kept_sections[h]:
                if p:
                    lines += [" ".join(p), ""]
    markdown = "\n".join(lines).rstrip() + "\n"
    return VerifiedDraft(markdown, report, find_placeholders(markdown))


# --- Academic CV: assembled from accepted entries only (no model) -----------------------------

CV_ORDER: tuple[tuple[Section, str], ...] = (
    (Section.EDUCATION, "Education"),
    (Section.RESEARCH, "Research experience"),
    (Section.PUBLICATION, "Publications"),
    (Section.EMPLOYMENT, "Professional experience"),
    (Section.PROJECT, "Projects"),
    (Section.AWARD, "Awards and honours"),
    (Section.PATENT, "Patents"),
    (Section.CERTIFICATION, "Certifications"),
    (Section.LEADERSHIP, "Leadership"),
    (Section.VOLUNTEER, "Volunteering"),
    (Section.MEMBERSHIP, "Memberships"),
)


def _dates(data: dict[str, Any]) -> str:
    start, end = data.get("start"), data.get("end")
    if start and end:
        return f"{start} \u2013 {'present' if end == 'present' else end}"
    return str(start or end or data.get("date") or data.get("year") or "")


def _cv_line(section: Section, data: dict[str, Any]) -> str:
    label = fact_label(section, data)
    extra: list[str] = []
    if section is Section.PUBLICATION:
        label = data["title"]
        extra = [str(v) for v in (data.get("authors"), data.get("venue"), data.get("doi")) if v]
    elif section in (Section.EDUCATION,):
        extra = [
            str(v)
            for v in (data.get("grade") and f"Grade: {data['grade']}", data.get("location"))
            if v
        ]
    elif section in (Section.RESEARCH, Section.PROJECT):
        extra = [str(v) for v in (data.get("organization"), data.get("role")) if v]
    elif section in (Section.AWARD, Section.CERTIFICATION):
        extra = [str(v) for v in (data.get("issuer"),) if v]
    when = _dates(data)
    parts = [f"**{label}**"] + extra + ([when] if when else [])
    line = ", ".join(parts)
    if data.get("description"):
        line += f"  \n{_clean(str(data['description']))[:600]}"
    return f"- {line}"


SKILLS = "skills"  # marker in an order: where the skills line goes

RESUME_ORDER: tuple[tuple[Section | str, str], ...] = (
    (Section.EMPLOYMENT, "Experience"),
    (Section.PROJECT, "Projects"),
    (SKILLS, "Skills"),
    (Section.EDUCATION, "Education"),
    (Section.CERTIFICATION, "Certifications"),
    (Section.AWARD, "Awards"),
    (Section.RESEARCH, "Research"),
    (Section.PUBLICATION, "Publications"),
    (Section.LEADERSHIP, "Leadership"),
    (Section.VOLUNTEER, "Volunteering"),
)


def assemble_academic_cv(name: str, facts: list[dict[str, Any]]) -> VerifiedDraft:
    """Academic CV: education and research first."""
    return _assemble(name, facts, (*CV_ORDER, (SKILLS, "Skills")))


def assemble_resume(name: str, facts: list[dict[str, Any]]) -> VerifiedDraft:
    """Job resume: experience, projects and skills first."""
    return _assemble(name, facts, RESUME_ORDER)


def _assemble(
    name: str, facts: list[dict[str, Any]], order: tuple[tuple[Section | str, str], ...]
) -> VerifiedDraft:
    """Every line comes from one accepted entry; the report maps lines to entry ids."""
    by_section: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        by_section.setdefault(f["section"], []).append(f)
    lines = [f"# {name}", "", placeholder("contact details (email, phone, city)"), ""]
    claims: list[dict[str, Any]] = []
    summary = by_section.get(Section.SUMMARY.value, [])
    if summary:
        lines += ["## Profile", "", _clean(str(summary[0]["data"]["text"])), ""]
        claims.append({"text": "Profile", "fact_ids": [summary[0]["id"]]})
    for section, heading in order:
        if section == SKILLS:
            skills = by_section.get(Section.SKILL.value, [])
            if skills:
                lines += [
                    f"## {heading}",
                    "",
                    ", ".join(str(f["data"]["name"]) for f in skills),
                    "",
                ]
                claims.append({"text": heading, "fact_ids": [f["id"] for f in skills]})
            continue
        assert isinstance(section, Section)
        rows = by_section.get(section.value, [])
        if not rows:
            continue
        lines += [f"## {heading}", ""]
        for f in rows:
            line = _cv_line(section, f["data"])
            lines.append(line)
            claims.append({"text": line[2:120], "fact_ids": [f["id"]]})
        lines.append("")
    if len(claims) == 0:
        lines += [
            placeholder("No confirmed profile entries yet. Confirm entries on My Profile."),
            "",
        ]
    markdown = "\n".join(lines).rstrip() + "\n"
    report = {
        "claims": claims,
        "position": [],
        "to_check": [],
        "removed": [],
        "missing_sections": [],
        "assembled": True,
    }
    return VerifiedDraft(markdown, report, find_placeholders(markdown))
