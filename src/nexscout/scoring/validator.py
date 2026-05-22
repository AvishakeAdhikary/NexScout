"""Validator constants (§14 of plan.md) — verbatim.

Used by the tailor and cover-letter prompts (to instruct the LLM what is
banned) and by the ``validate_*`` functions (full validator logic lands in M5).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from ..core.profile import Profile

Mode = Literal["strict", "normal", "lenient"]

BANNED_WORDS: list[str] = [
    # Filler verbs and adjectives
    "passionate",
    "dedicated",
    "committed to",
    "utilizing",
    "utilize",
    "harnessing",
    "spearheaded",
    "spearhead",
    "orchestrated",
    "championed",
    "pioneered",
    "robust",
    "scalable solutions",
    "cutting-edge",
    "state-of-the-art",
    "best-in-class",
    "proven track record",
    "track record of success",
    "demonstrated ability",
    "strong communicator",
    "team player",
    "fast learner",
    "self-starter",
    "go-getter",
    "synergy",
    "cross-functional collaboration",
    "holistic",
    "transformative",
    "innovative solutions",
    "paradigm",
    "ecosystem",
    "proactive",
    "detail-oriented",
    "highly motivated",
    "seamless",
    "full lifecycle",
    "deep understanding",
    "extensive experience",
    "comprehensive knowledge",
    "thrives in",
    "excels at",
    "adept at",
    "well-versed in",
    "i am confident",
    "i believe",
    "i am excited",
    "plays a critical role",
    "instrumental in",
    "integral part of",
    "strong track record",
    "eager to",
    "eager",
    # Cover-letter-specific
    "this demonstrates",
    "this reflects",
    "i have experience with",
    "furthermore",
    "additionally",
    "moreover",
]

LLM_LEAK_PHRASES: list[str] = [
    "i am sorry",
    "i apologize",
    "i will try",
    "let me try",
    "i am at a loss",
    "i am truly sorry",
    "apologies for",
    "i keep fabricating",
    "i will have to admit",
    "one final attempt",
    "one last time",
    "if it fails again",
    "persistent errors",
    "i am having difficulty",
    "i made an error",
    "my mistake",
    "here is the corrected",
    "here is the revised",
    "here is the updated",
    "here is my",
    "below is the",
    "as requested",
    "note:",
    "disclaimer:",
    "important:",
    "i have rewritten",
    "i have removed",
    "i have fixed",
    "i have replaced",
    "i have updated",
    "i have corrected",
    "per your feedback",
    "based on your feedback",
    "as per the instructions",
    "the following resume",
    "the resume below",
    "the following cover letter",
    "the letter below",
]

FABRICATION_WATCHLIST: set[str] = {
    # Languages outside a typical SWE candidate's stack
    "c#",
    "c++",
    "golang",
    "rust",
    "ruby",
    "kotlin",
    "swift",
    "scala",
    "matlab",
    # Frameworks for wrong languages
    "spring",
    "django",
    "rails",
    "angular",
    "vue",
    "svelte",
    # Hard lies — certifications can't be stretched
    "certif",
    "certified",
    "pmp",
    "scrum master",
    "aws certified",
}

REQUIRED_SECTIONS: set[str] = {"SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"}


def sanitize_text(t: str) -> str:
    """Replace smart quotes / em+en dashes with ASCII equivalents."""
    t = t.replace(" — ", ", ").replace("—", ", ")  # em dash
    t = t.replace("–", "-")  # en dash
    t = t.replace("“", '"').replace("”", '"')  # smart double quotes
    t = t.replace("‘", "'").replace("’", "'")  # smart single quotes
    return t.strip()


def has_banned_word(text: str) -> str | None:
    """Return the first banned word found in ``text`` (case-insensitive), or None."""
    lower = text.lower()
    for w in BANNED_WORDS:
        if re.search(r"\b" + re.escape(w) + r"\b", lower):
            return w
    return None


def has_leak_phrase(text: str) -> str | None:
    """Return the first LLM-leak phrase found (substring match), or None."""
    lower = text.lower()
    for p in LLM_LEAK_PHRASES:
        if p in lower:
            return p
    return None


def has_fabrication(text: str) -> str | None:
    """Return the first fabrication-watchlist term found in ``text``, or None."""
    lower = text.lower()
    for term in FABRICATION_WATCHLIST:
        if re.search(r"\b" + re.escape(term) + r"\b", lower):
            return term
    return None


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class ValidationResult:
    """Outcome of a validation pass.

    ``errors`` are hard failures (always reject in any mode that examines
    them); ``warnings`` are advisory and downgraded by mode.
    """

    __slots__ = ("errors", "warnings")

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok

    def messages(self) -> list[str]:
        return [*self.errors, *self.warnings]

    def merge(self, other: ValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------


def _record_banned(result: ValidationResult, text: str, *, mode: Mode, where: str) -> None:
    """Apply the mode policy for banned words to a single text blob."""
    if mode == "lenient":
        return
    found = has_banned_word(text)
    if not found:
        return
    msg = f"banned word {found!r} in {where}"
    if mode == "strict":
        result.errors.append(msg)
    else:
        result.warnings.append(msg)


def _record_leak(result: ValidationResult, text: str, *, where: str) -> None:
    """LLM leak phrases are always errors (any mode)."""
    found = has_leak_phrase(text)
    if found:
        result.errors.append(f"LLM leak phrase {found!r} in {where}")


# ---------------------------------------------------------------------------
# Tailor JSON validator
# ---------------------------------------------------------------------------


_REQUIRED_KEYS: tuple[str, ...] = ("title", "summary", "skills", "experience", "projects", "education")


def _stringify_block(value: Any) -> str:
    """Flatten any tailor JSON value to a single string for scanning."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_stringify_block(v) for v in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {_stringify_block(v)}" for k, v in value.items())
    return str(value)


def validate_json_fields(data: dict[str, Any] | None, profile: Profile, mode: Mode = "normal") -> ValidationResult:
    """Validate the tailor's JSON document.

    Required keys must be present and non-empty. Skills block must not contain
    any fabrication watchlist entry. Every preserved company name must appear
    in some ``experience.header``. The preserved school must appear in
    ``education``. LLM leak phrases are always errors. Banned words are an
    error in strict, a warning in normal, ignored in lenient.
    """
    result = ValidationResult()
    if not isinstance(data, dict):
        result.errors.append("tailor JSON missing or not an object")
        return result

    for key in _REQUIRED_KEYS:
        if key not in data or not data[key]:
            result.errors.append(f"missing or empty field: {key}")

    skills_text = _stringify_block(data.get("skills"))
    fab = has_fabrication(skills_text)
    if fab:
        result.errors.append(f"fabrication-watchlist term in skills: {fab!r}")

    experience = data.get("experience") or []
    headers = " | ".join(str(item.get("header", "")) for item in experience if isinstance(item, dict)).lower()
    for company in profile.facts.companies:
        if company and company.lower() not in headers:
            result.errors.append(f"preserved company missing from experience: {company!r}")

    education_text = _stringify_block(data.get("education")).lower()
    if profile.facts.school and profile.facts.school.lower() not in education_text:
        result.errors.append(f"preserved school missing from education: {profile.facts.school!r}")

    full_text = _stringify_block(data)
    _record_leak(result, full_text, where="resume")
    _record_banned(result, full_text, mode=mode, where="resume")
    return result


# ---------------------------------------------------------------------------
# Cover-letter validator
# ---------------------------------------------------------------------------


_DASH_RE = re.compile(r"[—–]")


def validate_cover_letter(text: str, profile: Profile, mode: Mode = "normal") -> ValidationResult:
    """Validate a cover letter per §12.2.

    Rules:

    * Must start with ``Dear``.
    * No em or en dashes anywhere.
    * Banned-word severity depends on ``mode``.
    * Word count <= 275 in normal, 250 in strict.
    * Must not contain LLM leak phrases (always an error).
    * Must not mention any tool outside ``profile.skills.all_skills()`` — but
      that's enforced indirectly by the fabrication watchlist.
    """
    result = ValidationResult()
    body = text.lstrip()
    if not body.lower().startswith("dear"):
        result.errors.append("cover letter must start with 'Dear'")
    if _DASH_RE.search(body):
        result.errors.append("em/en dashes are banned in cover letters")

    word_count = len(body.split())
    cap = 250 if mode == "strict" else 275
    if word_count > cap:
        result.errors.append(f"cover letter too long: {word_count} > {cap} words")

    _record_leak(result, body, where="cover letter")
    _record_banned(result, body, mode=mode, where="cover letter")

    fab = has_fabrication(body)
    if fab:
        # Fabrication is severity-dependent for cover letters too.
        msg = f"fabrication-watchlist term in cover letter: {fab!r}"
        if mode == "lenient":
            result.warnings.append(msg)
        else:
            result.errors.append(msg)

    _ = profile  # currently unused; kept for forward compatibility with skill scans
    return result
