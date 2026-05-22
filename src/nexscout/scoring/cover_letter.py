"""Stage 5 — Cover Letter (§12 of plan.md).

Verbatim §12.2 prompt. Strip any preamble before the first ``Dear``. Validate
via :func:`validate_cover_letter`. Word cap is 275 in normal, 250 in strict.
Up to 3 retries, each a fresh conversation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.profile import Profile
from ..llm.providers.base import Message
from .validator import (
    BANNED_WORDS,
    LLM_LEAK_PHRASES,
    Mode,
    sanitize_text,
    validate_cover_letter,
)

if TYPE_CHECKING:
    from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

MAX_COVER_RETRIES = 3


COVER_PROMPT_TEMPLATE = """Write a cover letter for {pref}. The goal is to get an interview.

STRUCTURE: 3 short paragraphs. Under 250 words. Every sentence must earn its place.

P1 (2-3 sentences): Open with a specific thing YOU built that solves THEIR
problem. Not "I'm excited about this role." Start with the work.

P2 (3-4 sentences): Pick 2 achievements from the resume most relevant to THIS
job. Use numbers. Frame as solving their problem.
Known projects: {projects}
Real metrics: {metrics}

P3 (1-2 sentences): One specific thing about the company from the job
description (product, technical challenge, team structure). Then close.
"Happy to walk through any of this in more detail." or "Let's discuss."

BANNED WORDS (validator rejects ANY of these):
{banned_words}

ALSO BANNED (meta-commentary):
{leak_phrases}

BANNED PUNCTUATION: No em dashes (—) or en dashes (–). Use commas or periods.

VOICE:
- Write like a real engineer emailing someone they respect.
- Never narrate or explain ("This demonstrates my commitment to X" → bad).
- Never hedge ("might address some of your challenges" → bad).
- Every sentence should contain a number, a tool name, or a specific outcome.

FABRICATION = INSTANT REJECTION:
Allowed tools are ONLY: {all_skills}
Do NOT mention ANY tool not in this list. If the job asks for tools not listed,
talk about the work you did, not the tools.

Sign off: just "{pref}"

Output ONLY the letter text. No subject lines. No "Here is the letter:".
Start DIRECTLY with "Dear Hiring Manager," and end with the name."""


USER_PAYLOAD_TEMPLATE = """JOB TITLE: {title}
COMPANY: {site}
LOCATION: {location}

DESCRIPTION:
{description}

CANDIDATE RESUME:
{resume_text}

Write the cover letter:"""


def build_cover_system_prompt(profile: Profile) -> str:
    """Substitute profile values into the verbatim §12.2 system prompt."""
    return COVER_PROMPT_TEMPLATE.format(
        pref=profile.me.pref,
        projects=", ".join(profile.facts.projects),
        metrics=", ".join(profile.facts.metrics),
        banned_words=", ".join(BANNED_WORDS),
        leak_phrases=", ".join(LLM_LEAK_PHRASES),
        all_skills=", ".join(profile.skills.all_skills()),
    )


def build_cover_user_payload(profile: Profile, job: dict[str, Any]) -> str:
    description = (job.get("full_description", "") or "")[:6000]
    return USER_PAYLOAD_TEMPLATE.format(
        title=job.get("title", ""),
        site=job.get("site", ""),
        location=job.get("location", ""),
        description=description,
        resume_text=profile.to_resume_text(),
    )


def strip_preamble(text: str) -> str:
    """Drop everything before the first ``Dear``."""
    if not text:
        return ""
    idx = text.find("Dear")
    if idx <= 0:
        return text.strip()
    return text[idx:].strip()


@dataclass
class CoverLetterResult:
    status: str  # "approved" | "failed_validation"
    text: str = ""
    attempts: int = 0
    errors: list[str] = field(default_factory=list)


def write_cover_letter(
    *,
    router: LLMRouter,
    profile: Profile,
    job: dict[str, Any],
    mode: Mode = "normal",
    max_retries: int = MAX_COVER_RETRIES,
) -> CoverLetterResult:
    """Generate, validate, and (on failure) retry a cover letter."""
    system_prompt = build_cover_system_prompt(profile)
    user_payload = build_cover_user_payload(profile, job)
    avoid_notes: list[str] = []
    last_errors: list[str] = []
    last_text = ""

    for attempt in range(1, max_retries + 1):
        sys_prompt = system_prompt
        if avoid_notes:
            sys_prompt = (
                system_prompt + "\n\n## AVOID THESE ISSUES (from previous attempt):\n- " + "\n- ".join(avoid_notes)
            )
        messages: list[Message] = [
            Message(role="system", content=sys_prompt),
            Message(role="user", content=user_payload),
        ]
        try:
            raw = router.ask("cover", messages, temperature=0.4, max_tokens=1024)
        except Exception as e:  # pragma: no cover — provider already retries
            last_errors = [f"router error: {e}"]
            continue

        letter = sanitize_text(strip_preamble(raw))
        report = validate_cover_letter(letter, profile, mode)
        last_text = letter
        if report.ok:
            return CoverLetterResult(status="approved", text=letter, attempts=attempt)
        last_errors = report.errors
        avoid_notes = list(last_errors)

    return CoverLetterResult(
        status="failed_validation",
        text=last_text,
        attempts=max_retries,
        errors=last_errors,
    )


__all__ = [
    "COVER_PROMPT_TEMPLATE",
    "MAX_COVER_RETRIES",
    "USER_PAYLOAD_TEMPLATE",
    "CoverLetterResult",
    "build_cover_system_prompt",
    "build_cover_user_payload",
    "strip_preamble",
    "write_cover_letter",
]
