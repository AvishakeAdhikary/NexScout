"""Planning how to fill an application form. Pure: discovered fields + what we know → a plan.

Rules (spec §7, AGENTS.md non-negotiables):
- Only values the user provided or confirmed are used: account name/email, the user's own
  answers, and documents the user selected. Nothing is invented; a required question without an
  answer stops the run (`missing`).
- Declarations/attestations ("I confirm the information is accurate") are never ticked while
  filling. They are ticked only at submit time, after the user approved exactly this plan.
- Optional checkboxes (newsletters, marketing) are left alone.
- Password fields and CAPTCHAs are blockers: NexScout never logs in or solves challenges.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

ATTESTATION = re.compile(
    r"\b(i (hereby )?(confirm|declare|certify|attest|agree)|accurate|true and (correct|complete)|"
    r"truthful)\b",
    re.I,
)
CAPTCHA_TEXT = re.compile(
    r"captcha|verify (that )?you('| a)re (a )?human|i'?m not a robot|are you a robot", re.I
)
CONFIRMATION = re.compile(
    r"application (has been |was )?(received|submitted)|thank you for (your application|applying)"
    r"|we have received your application",
    re.I,
)
REFERENCE = re.compile(
    r"\b(?:reference(?: number)?|ref\.?|application (?:id|number)|confirmation (?:number|code))"
    r"[\s:#]*([A-Z0-9][A-Z0-9-]{3,})",
    re.I,
)


@dataclass(frozen=True)
class FormField:
    key: str  # CSS selector that identifies the element on the page
    label: str
    kind: str  # text, email, tel, textarea, file, checkbox, select, password, ...
    required: bool = False
    name: str = ""


@dataclass
class Applicant:
    full_name: str
    email: str
    phone: str | None = None
    answers: dict[str, str] = field(default_factory=dict)  # normalized question → answer
    files: dict[str, dict[str, str]] = field(default_factory=dict)  # role → {path, title}


@dataclass
class PlannedField:
    key: str
    label: str
    kind: str
    action: str  # fill | upload | check_on_submit | skip
    value: str | None
    source: str
    required: bool


@dataclass
class FormPlan:
    fields: list[PlannedField]
    missing: list[str]
    attestations: list[str]

    def digest(self) -> str:
        """Stable fingerprint of what will be entered (file paths excluded, titles kept)."""
        rows = [
            (f.key, f.action, f.value if f.action != "upload" else f.source)
            for f in self.fields
            if f.action != "skip"
        ]
        return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

    def summary(self) -> list[dict[str, Any]]:
        """For the approval screen (no file paths)."""
        out = []
        for f in self.fields:
            row = asdict(f)
            if f.action == "upload":
                row["value"] = f.source
            out.append(row)
        return out


def normalize_question(label: str) -> str:
    text = re.sub(r"[*:]+", " ", label.lower())
    return re.sub(r"\s+", " ", text).strip()


def _is(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def plan_form(fields: list[FormField], who: Applicant) -> FormPlan:
    planned: list[PlannedField] = []
    missing: list[str] = []
    attestations: list[str] = []
    for f in fields:
        text = f"{f.label} {f.name}".lower()
        q = normalize_question(f.label)

        def add(action: str, value: str | None, source: str, f: FormField = f) -> None:
            planned.append(PlannedField(f.key, f.label, f.kind, action, value, source, f.required))

        if f.kind in ("hidden", "submit", "button", "reset", "image", "password"):
            continue
        if f.kind == "checkbox":
            if ATTESTATION.search(f.label):
                add("check_on_submit", "yes", "your approval")
                attestations.append(f.label)
            else:
                add("skip", None, "left as is")
            continue
        if f.kind == "file":
            role = (
                "cover_letter"
                if "cover" in text
                else ("cv" if _is(text, r"\bcv\b", r"r[ée]sum[ée]", r"curriculum") else None)
            )
            doc = who.files.get(role) if role else None
            if doc:
                add("upload", doc["path"], doc["title"])
            elif f.required:
                missing.append(f.label)
            else:
                add("skip", None, "no document selected")
            continue
        if q in who.answers and who.answers[q].strip():
            add("fill", who.answers[q].strip(), "your answer")
        elif f.kind == "email" or _is(text, r"e-?mail"):
            add("fill", who.email, "your account")
        elif _is(text, r"full name", r"^name\b", r"your name", r"\bname\b") and not _is(
            text, r"company", r"user ?name", r"referr", r"school", r"employer"
        ):
            add("fill", who.full_name, "your account")
        elif _is(text, r"phone", r"mobile", r"\btel"):
            if who.phone:
                add("fill", who.phone, "your answer")
            elif f.required:
                missing.append(f.label)
            else:
                add("skip", None, "not provided")
        elif f.required:
            missing.append(f.label)
        else:
            add("skip", None, "not answered")
    return FormPlan(planned, missing, attestations)


def detect_blocker(text: str, has_password: bool, has_captcha_frame: bool) -> str | None:
    if has_captcha_frame or CAPTCHA_TEXT.search(text):
        return "captcha"
    if has_password:
        return "login"
    return None


def detect_confirmation(text: str) -> tuple[bool, str | None]:
    confirmed = bool(CONFIRMATION.search(text))
    ref = REFERENCE.search(text)
    return confirmed, (ref.group(1) if ref and confirmed else None)
