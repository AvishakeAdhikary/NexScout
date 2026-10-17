# NexScout Product Requirements

The full original specification is the "master prompt" (§1–24) given at project start. This document
condenses it into requirement IDs, user journeys and acceptance criteria. When behaviour is
ambiguous, the stricter reading (safety, truthfulness, privacy) applies.

## 1. Users
People who are not experts in AI or automation, managing PhD and/or job searches. The UI explains what is
happening, why something was recommended, what evidence supports it, and what needs their action.
Advanced diagnostics are opt-in.

## 2. Requirements (IDs referenced by tests and the roadmap)
### Accounts and cases
- **R-ACC-1** Register, log in and log out. Sessions expire and are revocable.
- **R-ACC-2** Create, rename, describe, pause and archive candidate cases. Cases are fully isolated.
- **R-ACC-3** Export all of my data. Delete a case or the whole account.
### Profile
- **R-PRO-1** Profile sections (§4.2) editable through structured forms.
- **R-PRO-2** Import PDF, Markdown and DOCX. Original kept. Extracted facts reviewed before acceptance.
- **R-PRO-3** Each fact shows its status (user-entered, extracted, inferred, verified, external) and its source.
- **R-PRO-4** Mark facts private. Private facts are never sent to external parties without approval.
- **R-PRO-5** Social/profile URLs validated. No access-control bypass.
- **R-PRO-6** Preferences, including optional sensitive attributes (private by default, excluded from scoring).
- **R-PRO-7** Affiliation relationship table with usage permissions.
- **R-PRO-8** Missing-information detection.
### Mind map
- **R-MAP-1** Interactive, evidence-linked mind map with a table alternative.
- **R-MAP-2** Manual edits survive regeneration. Snapshots can be compared.
### Career path
- **R-PATH-1** Choose PhD, employment or both. Changeable without data loss.
### PhD pipeline
- **R-PHD-1** Discover programs, positions and faculty via configured, permitted sources.
- **R-PHD-2** Requirement research with provenance, freshness and uncertainty.
- **R-PHD-3** Generate SOP, research proposal, academic CV, inquiry emails, with placeholders for missing info.
- **R-PHD-4** Verify every claim against accepted facts.
- **R-DOC-1** Documents follow the conventions of the position's country (format, paper size, length,
  layout). Fall back to an international format when the location is unknown. The user can override
  the format.
- **R-DOC-2** Rendered documents are checked against the posting's stated requirements (blocking)
  and the format's conventions (warnings) before they can be uploaded.
### Jobs
- **R-JOB-1** Source registry (enable, disable, configure).
- **R-JOB-2** Normalization, entity resolution and deduplication. Repeated searches don't re-surface duplicates.
- **R-JOB-3** Strict and flexible experience modes with disclosed gaps.
- **R-JOB-4** Explainable match scores.
- **R-JOB-5** Referral suggestions only from permitted affiliations.
- **R-JOB-6** Tailored resume, cover letter and outreach drafts.
### Automation and tracking
- **R-AUTO-1** Browser automation fills forms. Final submit needs approval.
- **R-AUTO-2** Never bypass CAPTCHA or MFA. Manual takeover is available.
- **R-AUTO-3** Submission is confirmed only by observed evidence or the user. Otherwise it is "uncertain".
- **R-TRK-1** Application state machine, timeline, reminders, bulk actions and export.
### Workflow control
- **R-WF-1** Start, pause, resume, cancel, retry, rerun a step, approve or reject, skip an optional step.
- **R-WF-2** Survive restarts and crashes. No duplicate side effects.
- **R-WF-3** Live activity view: phase, completed steps, tool calls, retries, tokens and cost. No fake percentages.
### Providers
- **R-LLM-1** Mock, OpenAI-compatible (OpenAI, Ollama, LM Studio), Anthropic, Gemini. BYOK.
- **R-LLM-2** Works with 7–9B models via context budgeting and structured-output fallback.

## 3. Primary user journeys (E2E tests in `tests/e2e`)
1. Sign up → create case "My PhD search" → upload CV → review and accept facts → see the profile.
2. Open the mind map → click a node → see the evidence → edit the label → regenerate → the edit is kept.
3. Choose PhD → run discovery (fixture sources) → review the evidence → shortlist.
4. Generate an SOP → see placeholders and verifier flags → edit → render PDF and DOCX.
5. Approve the application → simulated submission on the fixture site → status `submitted` with evidence.
6. Pause a running workflow → resume → it completes. Simulate a worker crash → it recovers.
7. A second user cannot see any of user 1's data (UI and API).

## 4. Acceptance criteria
Per-milestone acceptance criteria are in [ROADMAP.md](ROADMAP.md). Feature-level criteria live
next to each requirement's tests.
