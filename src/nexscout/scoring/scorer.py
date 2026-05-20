"""Stage 3 — Scoring (§10 of plan.md).

Uses the verbatim system prompt from the plan. Parses ``SCORE:`` and clamps
the result to 1..10. Persists ``fit_score`` and ``score_reasoning`` via the
DB column registry.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ..core.profile import Profile
from ..llm.providers.base import Message
from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

# Verbatim system prompt (§10).
SYSTEM_PROMPT = """You are a job fit evaluator. Given a candidate's resume and a job description,
score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Direct experience in nearly all required skills.
- 7-8: Strong match. Most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (languages, frameworks, tools).
- Consider transferable experience (automation, scripting, API work).
- Factor in project experience.
- Be realistic about experience level vs. job requirements.

RESPOND IN EXACTLY THIS FORMAT (no other text):
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job description that match
           or could match the candidate]
REASONING: [2-3 sentences explaining the score]"""

_SCORE_RE = re.compile(r"SCORE:\s*(\d+)", re.IGNORECASE)
_KEYWORDS_RE = re.compile(r"KEYWORDS:\s*(.+?)(?:\n[A-Z]+:|\Z)", re.IGNORECASE | re.DOTALL)
_REASONING_RE = re.compile(r"REASONING:\s*(.+?)\Z", re.IGNORECASE | re.DOTALL)


def _build_user_payload(profile: Profile, job: dict[str, Any]) -> str:
    return (
        f"RESUME:\n{profile.to_resume_text()}\n\n"
        "---\n\n"
        "JOB POSTING:\n"
        f"TITLE: {job.get('title', '')}\n"
        f"COMPANY: {job.get('site', '')}\n"
        f"LOCATION: {job.get('location', '')}\n\n"
        f"DESCRIPTION:\n{(job.get('full_description', '') or '')[:6000]}"
    )


def _clamp(n: int) -> int:
    if n < 1:
        return 1
    if n > 10:
        return 10
    return n


def score_job(
    router: LLMRouter,
    profile: Profile,
    job: dict[str, Any],
    *,
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> tuple[int, str]:
    """Score a single job. Returns ``(score, reasoning)``.

    ``reasoning`` is ``"<keywords>\\n<reasoning>"`` as specified in §5.
    """
    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPT),
        Message(role="user", content=_build_user_payload(profile, job)),
    ]
    try:
        text = router.ask("score", messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as e:
        log.warning("scoring failed for %s: %s", job.get("url"), e)
        return 0, f"error: {e}"
    return _parse_score(text)


def _parse_score(text: str) -> tuple[int, str]:
    m = _SCORE_RE.search(text or "")
    score = _clamp(int(m.group(1))) if m else 0
    keywords_m = _KEYWORDS_RE.search(text or "")
    reasoning_m = _REASONING_RE.search(text or "")
    keywords = (keywords_m.group(1) if keywords_m else "").strip()
    reasoning = (reasoning_m.group(1) if reasoning_m else "").strip()
    combined = f"{keywords}\n{reasoning}".strip()
    return score, combined


def persist_score(conn: sqlite3.Connection, url: str, score: int, reasoning: str) -> None:
    """Persist the score to the ``jobs`` row identified by ``url``."""
    ts = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE jobs SET fit_score=?, score_reasoning=?, scored_at=? WHERE url=?",
        (score, reasoning, ts, url),
    )
