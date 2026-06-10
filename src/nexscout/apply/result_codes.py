"""Result codes for the apply agent (verbatim §13.3 of plan.md).

Each ``RESULT:`` line emitted by the ReAct loop maps to one of these constants.
The :data:`PERMANENT_FAILURE_REASONS` set + :data:`PERMANENT_PREFIXES` tuple
list the failure reasons that must never be retried; the orchestrator marks
those jobs with ``apply_attempts := 99`` so the acquire query never returns
them again.
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# Verbatim §13.3 result codes
# ---------------------------------------------------------------------------

# Top-level terminal statuses ("RESULT:APPLIED", etc.) — the agent prints
# these as bare strings when the application is submitted or terminally
# rejected.
RESULT_APPLIED = "APPLIED"
RESULT_EXPIRED = "EXPIRED"
RESULT_CAPTCHA = "CAPTCHA"
#: Job needs manual CAPTCHA solving — no provider configured. The orchestrator
#: parks the row with ``apply_status='captcha_manual'`` and writes a
#: pending_questions entry so the user (via OpenClaw / web UI) can finish it.
RESULT_CAPTCHA_MANUAL = "CAPTCHA_MANUAL"
RESULT_LOGIN_ISSUE = "LOGIN_ISSUE"

#: All terminal statuses (sans the ``FAILED:<reason>`` family).
TERMINAL_CODES: frozenset[str] = frozenset(
    {
        RESULT_APPLIED,
        RESULT_EXPIRED,
        RESULT_CAPTCHA,
        RESULT_CAPTCHA_MANUAL,
        RESULT_LOGIN_ISSUE,
    }
)

# ---------------------------------------------------------------------------
# RESULT:FAILED:<reason> reasons (verbatim §13.3).
# ---------------------------------------------------------------------------

FAIL_NOT_ELIGIBLE_LOCATION = "not_eligible_location"
FAIL_NOT_ELIGIBLE_WORK_AUTH = "not_eligible_work_auth"
FAIL_NOT_ELIGIBLE_SALARY = "not_eligible_salary"
FAIL_ALREADY_APPLIED = "already_applied"
FAIL_ACCOUNT_REQUIRED = "account_required"
FAIL_NOT_A_JOB_APPLICATION = "not_a_job_application"
FAIL_QUESTION_REQUIRED = "question_required"
FAIL_UNSAFE_PERMISSIONS = "unsafe_permissions"
FAIL_UNSAFE_VERIFICATION = "unsafe_verification"
FAIL_SSO_REQUIRED = "sso_required"
FAIL_SITE_BLOCKED = "site_blocked"
FAIL_CLOUDFLARE_BLOCKED = "cloudflare_blocked"
FAIL_STUCK = "stuck"
FAIL_PAGE_ERROR = "page_error"
FAIL_TIMEOUT = "timeout"
FAIL_NO_RESULT_LINE = "no_result_line"

#: Verbatim §13.3 / §5 permanent-failure reason list. Apply orchestrator
#: bumps ``apply_attempts := 99`` for any reason that lives here so the
#: atomic acquire query never returns the row again.
PERMANENT_FAILURE_REASONS: frozenset[str] = frozenset(
    {
        "expired",
        "captcha",
        "captcha_manual",
        "login_issue",
        FAIL_NOT_ELIGIBLE_LOCATION,
        FAIL_NOT_ELIGIBLE_SALARY,
        FAIL_ALREADY_APPLIED,
        FAIL_ACCOUNT_REQUIRED,
        FAIL_NOT_A_JOB_APPLICATION,
        FAIL_UNSAFE_PERMISSIONS,
        FAIL_UNSAFE_VERIFICATION,
        FAIL_SSO_REQUIRED,
        FAIL_SITE_BLOCKED,
        FAIL_CLOUDFLARE_BLOCKED,
        "blocked_by_cloudflare",
    }
)

#: Reasons that *start* with one of these are also permanent (§5: "any reason
#: that starts with site_blocked / cloudflare / blocked_by").
PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


def is_permanent_failure(reason: str | None) -> bool:
    """Return ``True`` if ``reason`` should freeze the job at attempts=99."""
    if not reason:
        return False
    r = reason.strip().lower()
    if r in PERMANENT_FAILURE_REASONS:
        return True
    return any(r.startswith(p) for p in PERMANENT_PREFIXES)


# ---------------------------------------------------------------------------
# Outcome taxonomy — classify every apply result into one of four buckets so
# the dashboard only ever shows *genuine* faults under "Problems".
# ---------------------------------------------------------------------------

#: A coarse bucket for an apply outcome. ``applied`` = success, ``parked`` =
#: needs a human (captcha/question), ``skipped`` = the posting just isn't
#: applicable/accessible (not a fault), ``error`` = a genuine fault that should
#: be RARE (page crash, infra failure, uncaught exception, no result line).
Outcome = Literal["applied", "parked", "skipped", "error"]

#: ``RESULT:FAILED:<reason>`` reasons that mean "needs the user, NOT an error".
#: These park the job; the user finishes it (captcha) or answers (question).
PARKED_REASONS: frozenset[str] = frozenset(
    {
        "captcha_manual",
        FAIL_QUESTION_REQUIRED,
    }
)

#: ``RESULT:FAILED:<reason>`` reasons that mean "skip — not a fit / not
#: accessible". The posting simply isn't applicable; this is a normal,
#: expected, benign outcome — never an error.
SKIPPED_REASONS: frozenset[str] = frozenset(
    {
        FAIL_NOT_ELIGIBLE_LOCATION,
        FAIL_NOT_ELIGIBLE_WORK_AUTH,
        FAIL_NOT_ELIGIBLE_SALARY,
        FAIL_ALREADY_APPLIED,
        FAIL_ACCOUNT_REQUIRED,
        FAIL_NOT_A_JOB_APPLICATION,
        FAIL_SSO_REQUIRED,
        FAIL_SITE_BLOCKED,
        FAIL_CLOUDFLARE_BLOCKED,
        "blocked_by_cloudflare",
        # Eligibility/verification gates the agent cannot safely pass — benign.
        FAIL_UNSAFE_PERMISSIONS,
        FAIL_UNSAFE_VERIFICATION,
        # Login walls / SSO are access gates, not faults.
        "login_issue",
        # An expired/closed posting is a normal non-fault skip.
        "expired",
    }
)

#: ``RESULT:FAILED:<reason>`` reasons that ARE genuine faults. Anything not in
#: PARKED/SKIPPED and not a clean terminal status falls here too (fail-safe is
#: NOT to call something an error — see :func:`classify_outcome`).
ERROR_REASONS: frozenset[str] = frozenset(
    {
        FAIL_PAGE_ERROR,
        FAIL_TIMEOUT,
        FAIL_NO_RESULT_LINE,
        "browser_launch_failed",
        "driver_error",
        "worker_crashed",
    }
)

#: Union of every reason we have explicitly judged to be benign (not an error).
#: Useful for callers that only need a yes/no "is this scary?" check.
BENIGN_REASONS: frozenset[str] = PARKED_REASONS | SKIPPED_REASONS


def classify_outcome(code: str | None, reason: str | None = None) -> Outcome:
    """Classify an apply ``(code, reason)`` pair into a coarse outcome bucket.

    The mapping mirrors the dashboard buckets: Applied / Waiting on you
    (parked) / Not a match (skipped) / Problems (error).

    * ``APPLIED`` → ``"applied"``.
    * ``CAPTCHA`` / ``CAPTCHA_MANUAL`` → ``"parked"`` (needs the user).
    * ``EXPIRED`` / ``LOGIN_ISSUE`` → ``"skipped"`` (benign, not applicable).
    * ``FAILED:<reason>`` → looked up in :data:`PARKED_REASONS` /
      :data:`SKIPPED_REASONS` / :data:`ERROR_REASONS`.

    Fail-*safe*: a ``FAILED`` with an *unknown* reason is treated as
    ``"skipped"`` (benign), NOT ``"error"`` — only reasons we have explicitly
    judged to be genuine faults (or an empty/absent result line) ever count as
    a Problem. This keeps the dashboard's "Problems" count honest.
    """
    c = (code or "").strip().upper()
    if c == RESULT_APPLIED:
        return "applied"
    if c in {RESULT_CAPTCHA, RESULT_CAPTCHA_MANUAL}:
        return "parked"
    if c in {RESULT_EXPIRED, RESULT_LOGIN_ISSUE}:
        return "skipped"

    r = (reason or "").strip().lower()
    if c.startswith("FAILED") or c == "":
        if r in PARKED_REASONS:
            return "parked"
        if r in ERROR_REASONS:
            return "error"
        if r in SKIPPED_REASONS:
            return "skipped"
        # No reason at all on a FAILED line == we never got a result → fault.
        if not r:
            return "error"
        # An unrecognised reason is benign by default (never scary).
        return "skipped"

    # Any other unknown code is benign by default.
    return "skipped"


def parse_result_line(line: str) -> tuple[str, str | None]:
    """Parse a ``RESULT:CODE[:reason]`` line emitted by the agent's ``done()``.

    Examples
    --------
    >>> parse_result_line("RESULT:APPLIED")
    ('APPLIED', None)
    >>> parse_result_line("RESULT:FAILED:sso_required")
    ('FAILED', 'sso_required')
    >>> parse_result_line("RESULT:FAILED:custom reason: trailing colon")
    ('FAILED', 'custom reason: trailing colon')
    """
    s = line.strip()
    if not s.startswith("RESULT:"):
        return ("FAILED", FAIL_NO_RESULT_LINE)
    body = s[len("RESULT:") :]
    if ":" in body:
        code, reason = body.split(":", 1)
        return code.strip().upper(), reason.strip() or None
    return body.strip().upper(), None


__all__ = [
    "BENIGN_REASONS",
    "ERROR_REASONS",
    "FAIL_ACCOUNT_REQUIRED",
    "FAIL_ALREADY_APPLIED",
    "FAIL_CLOUDFLARE_BLOCKED",
    "FAIL_NOT_A_JOB_APPLICATION",
    "FAIL_NOT_ELIGIBLE_LOCATION",
    "FAIL_NOT_ELIGIBLE_SALARY",
    "FAIL_NOT_ELIGIBLE_WORK_AUTH",
    "FAIL_NO_RESULT_LINE",
    "FAIL_PAGE_ERROR",
    "FAIL_QUESTION_REQUIRED",
    "FAIL_SITE_BLOCKED",
    "FAIL_SSO_REQUIRED",
    "FAIL_STUCK",
    "FAIL_TIMEOUT",
    "FAIL_UNSAFE_PERMISSIONS",
    "FAIL_UNSAFE_VERIFICATION",
    "PARKED_REASONS",
    "PERMANENT_FAILURE_REASONS",
    "PERMANENT_PREFIXES",
    "RESULT_APPLIED",
    "RESULT_CAPTCHA",
    "RESULT_CAPTCHA_MANUAL",
    "RESULT_EXPIRED",
    "RESULT_LOGIN_ISSUE",
    "SKIPPED_REASONS",
    "TERMINAL_CODES",
    "Outcome",
    "classify_outcome",
    "is_permanent_failure",
    "parse_result_line",
]
