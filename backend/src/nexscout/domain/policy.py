"""Autopilot policy: deterministic allow/deny decisions with reasons (pure).

"LLMs propose, deterministic code disposes": nothing here calls a model. Every decision lists
its reasons so the user can see why NexScout did, or didn't, act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from nexscout.domain.site_policy import SiteVerdict

STEPS = ("discover", "research", "documents", "fill", "submit")
DEFAULT_STEPS = {
    "discover": True,
    "research": True,
    "documents": True,
    "fill": True,
    "submit": False,
}
DEFAULT_DOC_TYPES = {"job": ["resume"], "academic": ["academic_cv"]}
# What the user agrees to when they turn on auto-submit (stored verbatim with the time).
AUTO_SUBMIT_CONSENT = (
    "I allow NexScout to submit applications for me without asking each time, but only to "
    "positions that match these settings, only with documents and answers I have provided or "
    "approved, only on sites that don't prohibit automated applications, and never past CAPTCHAs "
    "or sign-ins. I can stop it at any time."
)
DECLARATIONS_CONSENT = (
    "I allow NexScout to tick declarations such as 'I confirm the information is accurate' "
    "for me, because every value it enters comes from me."
)


@dataclass(frozen=True)
class Policy:
    enabled: bool
    steps: dict[str, bool]
    min_fit: int
    max_new_per_run: int
    daily_submit_cap: int
    per_org_cap: int
    countries: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()  # job | academic
    exclude_orgs: tuple[str, ...] = ()
    auto_submit: bool = False
    declarations: bool = False
    consented: bool = False

    def step(self, name: str) -> bool:
        return bool(self.enabled and self.steps.get(name, DEFAULT_STEPS.get(name, False)))


@dataclass(frozen=True)
class Candidate:
    opportunity_id: str
    title: str
    organization: str
    kind: str  # job | academic
    fit: int  # 0-100
    eligible: bool
    open: bool
    country: str | None = None
    deadline: date | None = None
    already_tracked: bool = False


@dataclass
class Verdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def consider(p: Policy, c: Candidate, *, today: date, org_count: int) -> Verdict:
    """Should the autopilot start working on this position?"""
    no: list[str] = []
    if not p.enabled:
        no.append("Autopilot is off.")
    if c.already_tracked:
        no.append("Already being worked on or applied to.")
    if not c.open:
        no.append("The position is closed.")
    if c.deadline and c.deadline < today:
        no.append("The deadline has passed.")
    if not c.eligible:
        no.append("You don't meet a stated requirement (see the match gaps).")
    if c.fit < p.min_fit:
        no.append(f"Fit {c.fit} is below your minimum of {p.min_fit}.")
    if p.kinds and c.kind not in p.kinds:
        no.append(f"You chose only {', '.join(p.kinds)} positions.")
    if p.countries and (c.country or "").upper() not in {x.upper() for x in p.countries}:
        no.append(f"Country {c.country or 'unknown'} isn't in your list.")
    if any(_norm(x) and _norm(x) in _norm(c.organization) for x in p.exclude_orgs):
        no.append(f"You excluded {c.organization}.")
    if org_count >= p.per_org_cap:
        no.append(f"Already {org_count} application(s) to {c.organization} (your limit).")
    if no:
        return Verdict(False, no)
    return Verdict(True, [f"Fit {c.fit} ≥ {p.min_fit}, open, eligible, within your limits."])


def shortlist(
    p: Policy, candidates: list[Candidate], *, today: date, org_counts: dict[str, int]
) -> list[tuple[Candidate, Verdict]]:
    """Best fit first, at most `max_new_per_run` taken; every candidate gets its reasons."""
    out: list[tuple[Candidate, Verdict]] = []
    taken = 0
    counts = dict(org_counts)
    for c in sorted(candidates, key=lambda c: (-c.fit, c.title)):
        v = consider(p, c, today=today, org_count=counts.get(_norm(c.organization), 0))
        if v.allowed and taken >= p.max_new_per_run:
            v = Verdict(False, [f"This run already took {p.max_new_per_run} new position(s)."])
        if v.allowed:
            taken += 1
            counts[_norm(c.organization)] = counts.get(_norm(c.organization), 0) + 1
        out.append((c, v))
    return out


@dataclass(frozen=True)
class SubmitContext:
    site: SiteVerdict
    submitted_today: int
    has_declarations: bool
    mock_documents: bool
    placeholders: bool
    unanswered: int


def may_auto_submit(p: Policy, ctx: SubmitContext) -> Verdict:
    """Can this filled form be submitted without asking? Otherwise a person approves it."""
    no: list[str] = []
    if not p.enabled:
        no.append("Autopilot is off.")
    if not (p.auto_submit and p.consented and p.step("submit")):
        no.append("You haven't allowed submitting without asking.")
    if ctx.site.mode != "auto":
        no.append(ctx.site.reason)
    if ctx.submitted_today >= p.daily_submit_cap:
        no.append(f"Daily limit reached ({p.daily_submit_cap}).")
    if ctx.has_declarations and not p.declarations:
        no.append("The form has a declaration and you asked to confirm those yourself.")
    if ctx.mock_documents:
        no.append("A document was written by the mock model, not by you or a real AI.")
    if ctx.placeholders:
        no.append("A document still has placeholders.")
    if ctx.unanswered:
        no.append("Some questions aren't answered.")
    if no:
        return Verdict(False, no)
    return Verdict(True, ["Within your autopilot settings: submitted without asking."])
