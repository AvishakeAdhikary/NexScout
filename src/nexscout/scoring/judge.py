"""Independent LLM resume judge (§11 verbatim prompt).

Catches LIES, not style changes. Defaults to the provider configured in
``profile.llm.judge``; the router resolves that under ``Task.judge``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from ..core.profile import Profile
from ..llm.providers.base import Message

if TYPE_CHECKING:
    from ..llm.router import LLMRouter

log = logging.getLogger(__name__)


JUDGE_SYSTEM_PROMPT = """You are a resume quality judge. A tailoring engine rewrote a resume to target
a specific job. Your job is to catch LIES, not style changes.

Answer EXACTLY:
VERDICT: PASS or FAIL
ISSUES: (list problems, or "none")

## CONTEXT — what the engine was instructed to do (ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch
- Reorder bullets and projects
- Reframe bullets to use the job's language
- Drop low-relevance bullets
- Reorder skills
- Change tone and wording extensively

## WHAT IS FABRICATION (FAIL):
1. Adding tools/languages/frameworks to TECHNICAL SKILLS that aren't allowed.
   Allowed skills are ONLY: {all_allowed_skills}
2. Inventing NEW metrics. Real metrics: {metrics}
3. Inventing work with no basis in any original bullet.
4. Adding companies, roles, degrees that don't exist.
5. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording, combining, or splitting bullets as long as the underlying work is real
- Describing the same work with different emphasis
- Dropping bullets
- Reordering anything
- Changing the title or summary completely

## TOLERANCE:
Allow up to 3 minor stretches (closely-related tool, slight metric rewording).
Only FAIL for MAJOR lies: invented projects, fake companies, fake degrees,
wildly inflated numbers, skills from a completely different domain.

Be strict about major lies. Lenient about minor stretches and learnable skills.
Do not fail for style/tone/restructuring."""


_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)
_ISSUES_RE = re.compile(r"ISSUES:\s*(.+?)\Z", re.IGNORECASE | re.DOTALL)


def build_judge_messages(profile: Profile, job: dict[str, Any], tailored_text: str) -> list[Message]:
    """Build the system + user messages for the judge call."""
    allowed = ", ".join(profile.skills.all_skills())
    metrics = ", ".join(profile.facts.metrics)
    system = JUDGE_SYSTEM_PROMPT.format(all_allowed_skills=allowed, metrics=metrics)
    user_payload = (
        f"JOB TITLE: {job.get('title', '')}\n\n"
        "ORIGINAL RESUME:\n"
        f"{profile.to_resume_text()}\n\n"
        "TAILORED RESUME:\n"
        f"{tailored_text}\n\n"
        "Judge this tailored resume:"
    )
    return [
        Message(role="system", content=system),
        Message(role="user", content=user_payload),
    ]


def parse_judge(text: str) -> tuple[str, str]:
    """Return ``(verdict, issues)``. Verdict defaults to ``"FAIL"`` on parse error."""
    verdict_m = _VERDICT_RE.search(text or "")
    issues_m = _ISSUES_RE.search(text or "")
    verdict = (verdict_m.group(1) if verdict_m else "FAIL").upper()
    issues = (issues_m.group(1) if issues_m else "").strip()
    return verdict, issues


def judge_resume(
    *,
    router: LLMRouter,
    profile: Profile,
    job: dict[str, Any],
    tailored_text: str,
) -> tuple[str, str]:
    """Call the judge LLM. Returns ``(verdict, issues)`` strings."""
    messages = build_judge_messages(profile, job, tailored_text)
    try:
        # 1024 (was 512) leaves room for reasoning models that emit a hidden
        # thinking channel before the PASS/FAIL verdict.
        text = router.ask("judge", messages, temperature=0.0, max_tokens=1024)
    except Exception as e:  # pragma: no cover — router already retries
        log.warning("judge call failed: %s", e)
        return "FAIL", f"judge error: {e}"
    return parse_judge(text)


__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "build_judge_messages",
    "judge_resume",
    "parse_judge",
]
