"""Result codes for the apply agent (verbatim §13.3 of plan.md).

Each ``RESULT:`` line emitted by the ReAct loop maps to one of these constants.
The :data:`PERMANENT_FAILURE_REASONS` set + :data:`PERMANENT_PREFIXES` tuple
list the failure reasons that must never be retried; the orchestrator marks
those jobs with ``apply_attempts := 99`` so the acquire query never returns
them again.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Verbatim §13.3 result codes
# ---------------------------------------------------------------------------

# Top-level terminal statuses ("RESULT:APPLIED", etc.) — the agent prints
# these as bare strings when the application is submitted or terminally
# rejected.
RESULT_APPLIED = "APPLIED"
RESULT_EXPIRED = "EXPIRED"
RESULT_CAPTCHA = "CAPTCHA"
RESULT_LOGIN_ISSUE = "LOGIN_ISSUE"

#: All terminal statuses (sans the ``FAILED:<reason>`` family).
TERMINAL_CODES: frozenset[str] = frozenset(
    {
        RESULT_APPLIED,
        RESULT_EXPIRED,
        RESULT_CAPTCHA,
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
    "FAIL_ACCOUNT_REQUIRED",
    "FAIL_ALREADY_APPLIED",
    "FAIL_CLOUDFLARE_BLOCKED",
    "FAIL_NOT_A_JOB_APPLICATION",
    "FAIL_NOT_ELIGIBLE_LOCATION",
    "FAIL_NOT_ELIGIBLE_SALARY",
    "FAIL_NOT_ELIGIBLE_WORK_AUTH",
    "FAIL_NO_RESULT_LINE",
    "FAIL_PAGE_ERROR",
    "FAIL_SITE_BLOCKED",
    "FAIL_SSO_REQUIRED",
    "FAIL_STUCK",
    "FAIL_TIMEOUT",
    "FAIL_UNSAFE_PERMISSIONS",
    "FAIL_UNSAFE_VERIFICATION",
    "PERMANENT_FAILURE_REASONS",
    "PERMANENT_PREFIXES",
    "RESULT_APPLIED",
    "RESULT_CAPTCHA",
    "RESULT_EXPIRED",
    "RESULT_LOGIN_ISSUE",
    "TERMINAL_CODES",
    "is_permanent_failure",
    "parse_result_line",
]
