"""Validator constants (§14 of plan.md) — verbatim.

Used by the tailor and cover-letter prompts (to instruct the LLM what is
banned) and by the ``validate_*`` functions (full validator logic lands in M5).
"""

from __future__ import annotations

import re

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
