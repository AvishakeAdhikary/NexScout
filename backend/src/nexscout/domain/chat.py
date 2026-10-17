"""The case assistant's intent router: a fixed menu, matched deterministically.

The assistant routes a message to the same use cases the screens use. It never performs a
consequential action (submit, send, pay, attest); for those it links to the screen where the
user approves them. Unknown requests get a list of what it can do; it never improvises facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Intent:
    name: str
    args: dict[str, str] = field(default_factory=dict)


_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("submit", re.compile(r"\b(submit|send|apply)\b.*\b(application|it|now|for me)\b", re.I)),
    (
        "needs_you",
        re.compile(
            r"what (needs|requires) (me|my attention)|what should i do|to-?do|needs? my (attention|"
            r"approval)|anything (for|waiting on) me",
            re.I,
        ),
    ),
    ("deadlines", re.compile(r"\b(deadlines?|due (soon|dates?)|upcoming)\b", re.I)),
    ("status", re.compile(r"\b(status|where (is|are) my|how is my|progress)\b", re.I)),
    (
        "find_phd",
        re.compile(
            r"\b(find|search|look for|discover)\b.*\b(phd|doctoral|postdoc|"
            r"research positions?|studentships?)\b",
            re.I,
        ),
    ),
    (
        "find_jobs",
        re.compile(
            r"\b(find|search|look for|discover)\b.*\b(jobs?|roles?|positions?|"
            r"openings?|vacanc\w+)\b",
            re.I,
        ),
    ),
    (
        "draft_academic_cv",
        re.compile(r"\b(make|create|draft|build|generate)\b.*\bacademic cv\b", re.I),
    ),
    (
        "draft_resume",
        re.compile(
            r"\b(make|create|draft|build|generate)\b.*\b(resume|r[ée]sum[ée]"
            r"|cv)\b",
            re.I,
        ),
    ),
    (
        "review_profile",
        re.compile(r"\b(review|check|confirm)\b.*\b(profile|entries|facts)\b", re.I),
    ),
    ("help", re.compile(r"^\s*(help|\?|what can you do|hi|hello|hey)\b", re.I)),
]
_STOP = {
    "my",
    "the",
    "application",
    "applications",
    "status",
    "of",
    "for",
    "on",
    "with",
    "is",
    "are",
    "where",
    "how",
    "progress",
    "what",
    "a",
    "an",
    "to",
    "at",
}


def classify(message: str) -> Intent:
    text = " ".join(message.split())[:500]
    for name, pattern in _RULES:
        m = pattern.search(text)
        if not m:
            continue
        if name == "status":
            words = [
                w.strip(".'-")
                for w in re.findall(r"[\w&.'-]+", text.lower())
                if w.strip(".'-") not in _STOP
            ]
            return Intent("status", {"q": " ".join(words)[:80]})
        return Intent(name)
    return Intent("unknown")


CAPABILITIES = [
    "“What needs me?”: approvals, blocked applications and entries to review",
    "“Upcoming deadlines”",
    "“Status of my application to Acme”",
    "“Find PhD positions” or “Find jobs”: searches your enabled sources",
    "“Create my resume” or “Create my academic CV”: assembled from confirmed entries",
    "“Review my profile”",
]
