"""Stage 4 — Tailoring (§11 of plan.md).

The LLM returns a JSON document; the **code** (never the LLM) assembles the
plain-text resume via :func:`assemble_resume_text`. Each retry starts a fresh
conversation. Up to 3 retries. After the validator passes (and judge passes
unless ``mode=='lenient'``) the result is "approved" — otherwise
``failed_validation`` or ``approved_with_judge_warning``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.profile import Profile
from ..discovery.smartextract import extract_json
from .validator import (
    BANNED_WORDS,
    FABRICATION_WATCHLIST,
    Mode,
    sanitize_text,
    validate_json_fields,
)

if TYPE_CHECKING:
    from ..llm.router import LLMRouter

log = logging.getLogger(__name__)

MAX_TAILOR_RETRIES = 3

# ---------------------------------------------------------------------------
# Verbatim §11 prompts
# ---------------------------------------------------------------------------

# System prompt template — uses ``{...}`` placeholders filled in by build_system_prompt.
SYSTEM_PROMPT_TEMPLATE = """You are a senior technical recruiter rewriting a resume to get this person
an interview.

Take the base resume and job description. Return a tailored resume as a JSON
object.

## RECRUITER SCAN (6 seconds):
1. Title — matches what they're hiring?
2. Summary — 2 sentences proving you've done this work
3. First 3 bullets of most recent role — verbs and outcomes match?
4. Skills — must-haves visible immediately?

## SKILLS BOUNDARY (real skills only):
Languages: {languages}
Frameworks: {frameworks}
Infra: {infra}
Data: {data}
Tools: {tools}

You MAY add 2-3 closely related tools (Kubernetes if Docker, Terraform if AWS,
Redis if PostgreSQL). No unrelated languages/frameworks.

## TAILORING RULES:
TITLE: Match the target role. Keep seniority (Senior/Lead/Staff). Drop suffixes.
SUMMARY: Rewrite from scratch. Lead with the 1-2 skills that matter most.
SKILLS: Reorder each category so the job's must-haves appear first.
Reframe EVERY bullet. Same real work, different angle. Never copy verbatim.
PROJECTS: Reorder by relevance. Drop irrelevant projects.
BULLETS: Strong verb + what you built + quantified impact. Vary verbs
(Built, Designed, Implemented, Reduced, Automated, Deployed, Operated,
Optimized). Most relevant first. Max 4 per section.

## VOICE:
- Write like a real engineer. Short, direct.
- GOOD: "Automated financial reporting with Python + API integrations,
        cut processing time from 10 hours to 2"
- BAD:  "Leveraged cutting-edge AI to drive transformative efficiencies"
- BANNED WORDS (any of these = validation failure):
  {banned_words}
- No em dashes. Use commas, periods, or hyphens.

## HARD RULES:
- Do NOT invent work, companies, degrees, certifications.
- Do NOT change real numbers ({metrics}).
- Preserved companies: {companies} — names stay as-is.
- Preserved school: {school}.
- Must fit 1 page.

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary. No
"here is" preamble.

{{"title":"Role Title",
 "summary":"2-3 tailored sentences.",
 "skills":{{"Languages":"...","Frameworks":"...","Infra":"...",
           "Data":"...","Tools":"..."}},
 "experience":[{{"header":"Title at Company","subtitle":"Tech | Dates",
                "bullets":["b1","b2","b3","b4"]}}],
 "projects":[{{"header":"Project — Description","subtitle":"Tech | Dates",
              "bullets":["b1","b2"]}}],
 "education":"{school} | {education}"}}"""


USER_PROMPT_TEMPLATE = """ORIGINAL RESUME:
{resume_text}

---

TARGET JOB:
TITLE: {title}
COMPANY: {site}
LOCATION: {location}

DESCRIPTION:
{description}

Return the JSON:"""


def build_system_prompt(profile: Profile) -> str:
    """Substitute profile values into the verbatim §11 system prompt."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        languages=", ".join(profile.skills.lang),
        frameworks=", ".join(profile.skills.fw),
        infra=", ".join(profile.skills.infra),
        data=", ".join(profile.skills.data),
        tools=", ".join(profile.skills.tools),
        banned_words=", ".join(BANNED_WORDS),
        metrics=", ".join(profile.facts.metrics),
        companies=", ".join(profile.facts.companies),
        school=profile.facts.school,
        education=profile.exp.edu,
    )


def build_user_payload(profile: Profile, job: dict[str, Any]) -> str:
    """Build the user payload exactly as specified in §11."""
    description = (job.get("full_description", "") or "")[:6000]
    return USER_PROMPT_TEMPLATE.format(
        resume_text=profile.to_resume_text(),
        title=job.get("title", ""),
        site=job.get("site", ""),
        location=job.get("location", ""),
        description=description,
    )


# ---------------------------------------------------------------------------
# Resume assembly
# ---------------------------------------------------------------------------


def _format_skills_block(skills: Any) -> list[str]:
    if not isinstance(skills, dict):
        return []
    lines: list[str] = []
    for category, value in skills.items():
        rendered = ", ".join(str(v) for v in value) if isinstance(value, list) else value
        if rendered:
            lines.append(f"{category}: {rendered}")
    return lines


def _format_section(section_data: Any) -> list[str]:
    """Render an EXPERIENCE / PROJECTS section block."""
    if not isinstance(section_data, list):
        return []
    lines: list[str] = []
    for item in section_data:
        if not isinstance(item, dict):
            continue
        header = str(item.get("header", "")).strip()
        subtitle = str(item.get("subtitle", "")).strip()
        if header:
            lines.append(header)
        if subtitle:
            lines.append(subtitle)
        bullets = item.get("bullets") or []
        if isinstance(bullets, list):
            for b in bullets:
                lines.append(f"- {b}")
        lines.append("")
    return lines


def assemble_resume_text(data: dict[str, Any], profile: Profile) -> str:
    """Produce the plain-text resume.

    The header is injected from the profile by code — the LLM never writes it.
    """
    me = profile.me
    github_url = f"https://{me.links.gh}" if me.links.gh and not me.links.gh.startswith("http") else me.links.gh
    linkedin_url = f"https://{me.links.li}" if me.links.li and not me.links.li.startswith("http") else me.links.li
    contact_parts = [p for p in (me.email, me.phone, github_url, linkedin_url) if p]

    lines: list[str] = [me.legal, str(data.get("title", "")), " | ".join(contact_parts), ""]

    lines.append("SUMMARY")
    lines.append(str(data.get("summary", "")).strip())
    lines.append("")

    lines.append("TECHNICAL SKILLS")
    lines.extend(_format_skills_block(data.get("skills")))
    lines.append("")

    lines.append("EXPERIENCE")
    lines.extend(_format_section(data.get("experience")))

    lines.append("PROJECTS")
    lines.extend(_format_section(data.get("projects")))

    lines.append("EDUCATION")
    lines.append(str(data.get("education", "")).strip())

    text = "\n".join(lines).rstrip() + "\n"
    return sanitize_text(text)


# ---------------------------------------------------------------------------
# Retry loop
# ---------------------------------------------------------------------------


@dataclass
class TailorResult:
    """Output of one tailoring attempt — bundle of artefacts + status."""

    status: str  # "approved" | "approved_with_judge_warning" | "failed_validation"
    data: dict[str, Any] | None = None
    text: str = ""
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    judge_verdict: str | None = None
    judge_issues: str | None = None


def tailor_resume(
    *,
    router: LLMRouter,
    profile: Profile,
    job: dict[str, Any],
    mode: Mode = "normal",
    run_judge: bool = True,
    max_retries: int = MAX_TAILOR_RETRIES,
) -> TailorResult:
    """Run the tailor loop; up to ``max_retries`` fresh conversations."""
    from .judge import judge_resume  # local import to avoid cycle on lenient mode

    system_prompt = build_system_prompt(profile)
    user_payload = build_user_payload(profile, job)
    avoid_notes: list[str] = []
    last_errors: list[str] = []
    last_data: dict[str, Any] | None = None
    last_text = ""

    for attempt in range(1, max_retries + 1):
        sys_prompt = system_prompt
        if avoid_notes:
            sys_prompt = (
                system_prompt
                + "\n\n## AVOID THESE ISSUES (from previous attempt):\n- "
                + "\n- ".join(avoid_notes)
            )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_payload},
        ]
        try:
            raw = router.ask("tailor", messages, temperature=0.3, max_tokens=4096)
        except Exception as e:  # pragma: no cover — provider already retries
            last_errors = [f"router error: {e}"]
            continue

        data = extract_json(raw)
        if not isinstance(data, dict):
            last_errors = ["LLM did not return valid JSON"]
            avoid_notes = list(last_errors)
            continue

        report = validate_json_fields(data, profile, mode)
        if not report.ok:
            last_errors = report.errors
            avoid_notes = list(last_errors)
            last_data = data
            last_text = assemble_resume_text(data, profile)
            continue

        last_data = data
        last_text = assemble_resume_text(data, profile)

        if mode == "lenient" or not run_judge:
            return TailorResult(status="approved", data=data, text=last_text, attempts=attempt)

        verdict, issues = judge_resume(
            router=router,
            profile=profile,
            job=job,
            tailored_text=last_text,
        )
        if verdict.upper() == "PASS":
            return TailorResult(
                status="approved",
                data=data,
                text=last_text,
                attempts=attempt,
                judge_verdict=verdict,
                judge_issues=issues,
            )
        # Judge failed — append issues to avoid notes and retry.
        last_errors = [f"judge fail: {issues}"]
        avoid_notes = list(last_errors)

    if last_data is not None and last_text:
        status = "approved_with_judge_warning" if "judge fail" in (last_errors[0] if last_errors else "") else (
            "failed_validation"
        )
        return TailorResult(
            status=status,
            data=last_data,
            text=last_text,
            attempts=max_retries,
            errors=last_errors,
        )
    return TailorResult(status="failed_validation", attempts=max_retries, errors=last_errors)


__all__ = [
    "BANNED_WORDS",
    "FABRICATION_WATCHLIST",
    "MAX_TAILOR_RETRIES",
    "SYSTEM_PROMPT_TEMPLATE",
    "USER_PROMPT_TEMPLATE",
    "TailorResult",
    "assemble_resume_text",
    "build_system_prompt",
    "build_user_payload",
    "tailor_resume",
]
