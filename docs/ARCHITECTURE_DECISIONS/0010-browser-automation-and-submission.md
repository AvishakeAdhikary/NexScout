# ADR-0010: Browser automation: fill, approve, submit at most once

- **Status:** Accepted
- **Date:** 2026-10-17

## Context
Submitting an application is a consequential external action (non-negotiable 4). Sites differ,
change without notice, use CAPTCHAs and logins, and don't always confirm a submission. A crash
between the click and the result must never lead to a second submission.

## Decision
- **Workflow `browser_apply`** (`agents/browser_apply.py`): fill → approve → submit.
  Playwright's sync API runs in a worker thread (Selector event loop on Windows).
- **Values come only from the user.** The form plan (`domain/forms.py`) uses the account name and
  email, the user's own answers (keyed by normalized question text), and the documents they chose,
  uploaded as rendered PDFs. Unanswered required fields stop the run (`needs_user_action`) and the
  questions are shown to the user. Optional checkboxes are never ticked.
- **Declarations** ("I confirm the information is accurate") are never ticked while filling. They
  are listed in the approval and ticked only at submit time, after approval.
- **Approval** shows every value, every file, the declarations and a screenshot. The decision is
  read from `approval_requests` (ADR-0008).
- **Submit guard.**
  - `AWAITING_REVIEW → APPROVED → SUBMITTING` is committed *before* the click.
  - On submit the page is filled again and must reproduce the approved plan fingerprint
    (`FormPlan.digest`); otherwise nothing is clicked and the application becomes `failed`.
  - If a run finds the application already `SUBMITTING` (a crash mid-submit), it moves to
    `submission_uncertain` and never clicks again.
  - The side-effect ledger records the attempt.
- **Outcome.**
  - `submitted` requires an observed confirmation (confirmation text plus reference) or the
    user's confirmation, recorded as `evidence.source = observed | user`.
  - Otherwise the application is `submission_uncertain` until the user resolves it, and it is
    never retried automatically.
- **Blockers.** A CAPTCHA or login page → `needs_user_action`, with instructions for the user to
  apply themselves and mark it submitted (manual takeover). NexScout doesn't store site
  passwords.
- **Network guard.** Every request from the page goes through `Guard`: public http(s) hosts only,
  plus the configured demo-site origin in dev and test.
- **Demo site** (`integrations/fixture_site.py`), mounted at `/fixture-site` outside production,
  clearly labelled. It has normal, CAPTCHA, login and unconfirmed variants, and keeps
  submissions in memory so tests can assert exactly-once.

## Consequences
- Only single-page HTML forms with labelled fields are supported. Multi-step wizards, custom
  JavaScript widgets and file pickers that aren't `<input type=file>` stop the run with a reason.
- Confirmation detection is English-only.
- A hard cancel can't stop a browser step that is already running in its thread; the step finishes
  first.
