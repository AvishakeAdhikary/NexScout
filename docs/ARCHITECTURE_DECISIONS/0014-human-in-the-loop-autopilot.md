# ADR-0014: Human-in-the-loop autopilot (standing approvals, reconciler, answer bank)

- **Status:** accepted (M12, 2026-10-17)
- **Context:** The user wants NexScout to work like an employee: find positions, prepare
  truthful documents, fill in long forms and submit, around the clock. It must still never
  guess, never invent facts, never bypass CAPTCHAs or sign-ins, and never get the user into
  trouble online. Questions and approvals reach the user on their phone (ADR-0013).

## Decision
1. **A per-case policy, off by default** (`autopilot_policies`).
   - It sets which steps may run unattended (discover, research, documents, fill, submit), plus
     thresholds and caps: minimum fit, new positions per run, submissions per day, per
     organization, countries, kinds, excluded organizations, and document types.
   - **Submitting without asking** needs the consent statement sent back word for word. The
     statement and the time are stored, and so is the declaration-ticking consent. Turning
     auto-submit off clears the consent.
2. **Deterministic decisions** (`domain/policy.py`, pure).
   - `consider` and `shortlist` decide which positions to take. Every candidate gets reasons,
     including the rejected ones, and those reasons are shown to the user.
   - `may_auto_submit` re-checks, at the moment of submission:
     - that consent exists and the submit step is on;
     - the site's verdict;
     - the daily cap;
     - declarations, if the form has them;
     - mock-written documents;
     - placeholders;
     - unanswered questions.
   - No model is involved in any of these decisions.
3. **Online compliance** (`domain/site_policy.py`).
   - Sites whose published terms prohibit bots or automated applications are **manual-only**
     whatever the user sets: LinkedIn, Indeed, Glassdoor, ZipRecruiter, Monster, Handshake,
     Wellfound, Meta, X, ResearchGate, Google Scholar, Upwork and Fiverr. So is any page that
     robots.txt disallows. NexScout prepares the documents and tells the user to apply there
     themselves.
   - Applicant-tracking portals (Workday, Greenhouse, Lever, …) and plain-http pages always get
     a human approval, unless the user explicitly allows auto-submit on portals.
   - At most one autopilot browser session per site per 10 minutes. CAPTCHAs and logins are
     never touched.
4. **A cycle workflow plus a level-triggered reconciler.**
   - `autopilot_cycle` (LangGraph, durable) runs discover → shortlist → report on the policy's
     schedule.
   - Each pick becomes an `autopilot_items` row. On every maintenance tick, the worker's
     reconciler moves each item one stage, by calling **the same use cases as the screens**:
     research → drafts → placeholder filling → render → application → fill → submit or approval.
   - Child runs are ordinary workflow runs, so they are durable, visible in Agent Activity,
     pausable and cancellable, and their approvals reach the user's channels.
   - Because the reconciler is level-triggered, a crash anywhere just resumes on the next tick.
5. **The answer bank** (`case_answers`).
   - Form questions and document placeholders become `question` notifications. The user
     answers in the app or by replying in a chat. Answers are stored once per normalized
     question and reused by the form planner and for placeholders.
   - Placeholders filled from the bank create a new, user-attributed document version.
   - Nothing is ever generated into an answer.
6. **The policy as approver, recorded.**
   - When `may_auto_submit` allows a submission, `record_policy_approval` stores an
     `approval_requests` row with status `approved` and the note "Approved by your autopilot
     settings.", and it is audited (`approval.decided_by_policy`).
   - A later `require_approval` for the same node finds that row, so replays stay consistent.
7. **Assisted mode** (`browser_assist`).
   - For a CAPTCHA or sign-in, NexScout opens a visible browser window on the user's computer
     (desktop or local install) with what it knows already filled in.
   - The person solves the challenge, checks everything, ticks declarations and submits.
     NexScout only watches for the confirmation, and records it as the person's submission.
8. **Kill switch.** "Stop everything" in the UI, or **STOP** sent from a paired chat, turns
   every policy off and cancels the autopilot's running work and cycles.
9. **Daily digest** on the user's channels: submitted, waiting for you, in progress.

## Consequences
- Fully unattended submission happens only with recorded consent, on sites with no published
  restriction, for complete documents written from the user's own data, within caps.
  Everything else becomes a one-tap approval or a question.
- Real job boards are mostly manual-only by their own terms. On those sites the autopilot's
  value is research, documents and tracking, not clicking submit.
- Live behaviour on real employer portals is unverified. Each portal differs, and the demo
  site is the only automated target in tests (KNOWN_LIMITATIONS).
