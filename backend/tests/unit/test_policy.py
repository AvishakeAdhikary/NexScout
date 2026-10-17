"""M12 pure rules: autopilot policy decisions and site automation verdicts."""

from datetime import date

from nexscout.application.autopilot import _missing_questions
from nexscout.domain.policy import (
    DEFAULT_STEPS,
    Candidate,
    Policy,
    SubmitContext,
    consider,
    may_auto_submit,
    shortlist,
)
from nexscout.domain.site_policy import SiteVerdict, site_verdict

TODAY = date(2026, 10, 17)


def _policy(**kw: object) -> Policy:
    base: dict[str, object] = {
        "enabled": True,
        "steps": {**DEFAULT_STEPS, "submit": True},
        "min_fit": 60,
        "max_new_per_run": 2,
        "daily_submit_cap": 3,
        "per_org_cap": 1,
    }
    base.update(kw)
    return Policy(**base)  # type: ignore[arg-type]


def _cand(i: int, **kw: object) -> Candidate:
    base: dict[str, object] = {
        "opportunity_id": str(i),
        "title": f"Job {i}",
        "organization": f"Org {i}",
        "kind": "job",
        "fit": 80,
        "eligible": True,
        "open": True,
        "country": "DE",
    }
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


def test_consider_lists_every_reason() -> None:
    v = consider(
        _policy(countries=("NL",), kinds=("academic",), exclude_orgs=("org 1",)),
        _cand(1, fit=40, eligible=False, open=False, deadline=date(2026, 1, 1)),
        today=TODAY,
        org_count=1,
    )
    assert not v.allowed
    text = " ".join(v.reasons)
    for part in (
        "closed",
        "deadline",
        "requirement",
        "below your minimum",
        "only academic",
        "isn't in your list",
        "excluded",
        "your limit",
    ):
        assert part in text, part


def test_shortlist_best_fit_first_with_caps() -> None:
    cands = [
        _cand(1, fit=70),
        _cand(2, fit=90),
        _cand(3, fit=85, organization="Org X"),
        _cand(4, fit=95),
    ]
    out = shortlist(_policy(max_new_per_run=2), cands, today=TODAY, org_counts={})
    taken = [c.opportunity_id for c, v in out if v.allowed]
    assert taken == ["4", "2"]  # best fit first; the third pick exceeds the per-run cap
    reasons = {c.opportunity_id: v.reasons for c, v in out}
    assert "already took 2" in reasons["3"][0]
    # Same organization twice: the per-organization cap applies within a run as well.
    out = shortlist(
        _policy(max_new_per_run=5),
        [_cand(1), _cand(2, organization="Org 1")],
        today=TODAY,
        org_counts={},
    )
    assert [v.allowed for _, v in out] == [True, False]


def test_disabled_policy_does_nothing() -> None:
    assert not consider(_policy(enabled=False), _cand(1), today=TODAY, org_count=0).allowed
    assert not _policy(enabled=False).step("discover")


def _ctx(**kw: object) -> SubmitContext:
    base: dict[str, object] = {
        "site": SiteVerdict("auto", "ok", "jobs.example.com"),
        "submitted_today": 0,
        "has_declarations": False,
        "mock_documents": False,
        "placeholders": False,
        "unanswered": 0,
    }
    base.update(kw)
    return SubmitContext(**base)  # type: ignore[arg-type]


def test_auto_submit_needs_consent_and_a_clean_context() -> None:
    consented = _policy(auto_submit=True, consented=True)
    assert may_auto_submit(consented, _ctx()).allowed
    assert not may_auto_submit(_policy(auto_submit=True, consented=False), _ctx()).allowed
    assert not may_auto_submit(_policy(), _ctx()).allowed
    no_submit_step = _policy(auto_submit=True, consented=True, steps={**DEFAULT_STEPS})
    assert not may_auto_submit(no_submit_step, _ctx()).allowed
    for bad in (
        {"site": SiteVerdict("approval", "portal", "x")},
        {"submitted_today": 3},
        {"has_declarations": True},
        {"mock_documents": True},
        {"placeholders": True},
        {"unanswered": 1},
    ):
        v = may_auto_submit(consented, _ctx(**bad))
        assert not v.allowed, bad
        assert v.reasons
    assert may_auto_submit(
        _policy(auto_submit=True, consented=True, declarations=True), _ctx(has_declarations=True)
    ).allowed


def test_site_verdicts() -> None:
    assert site_verdict("https://www.linkedin.com/jobs/view/1", robots_allows=True).mode == "manual"
    assert site_verdict("https://uk.indeed.com/viewjob?jk=1", robots_allows=True).mode == "manual"
    assert site_verdict("https://jobs.example.com/apply", robots_allows=False).mode == "manual"
    assert site_verdict("https://jobs.example.com/apply", robots_allows=None).mode == "approval"
    assert site_verdict("http://jobs.example.com/apply", robots_allows=True).mode == "approval"
    portal = "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1"
    assert site_verdict(portal, robots_allows=True).mode == "approval"
    assert site_verdict(portal, robots_allows=True, allow_ats_auto=True).mode == "auto"
    assert site_verdict("https://jobs.example.com/apply", robots_allows=True).mode == "auto"
    assert site_verdict("ftp://x/y", robots_allows=True).mode == "manual"
    demo = site_verdict(
        "http://127.0.0.1:8000/fixture-site/apply/1",
        robots_allows=None,
        demo_origin="http://127.0.0.1:8000/fixture-site",
    )
    assert demo.mode == "auto"
    # A look-alike host doesn't inherit the real one's verdict, and vice versa.
    assert site_verdict("https://notlinkedin.com/x", robots_allows=True).mode == "auto"


def test_missing_questions_parsed_from_blocker() -> None:
    from types import SimpleNamespace

    app = SimpleNamespace(
        blocker="The form asks for things NexScout has no answer for: Why us? *; Salary. "
        "Add your answers, then try again."
    )
    assert _missing_questions(app) == ["Why us? *", "Salary"]  # type: ignore[arg-type]
    assert _missing_questions(SimpleNamespace(blocker="CAPTCHA")) == []  # type: ignore[arg-type]
