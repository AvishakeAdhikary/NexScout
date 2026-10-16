# ADR-0009: Truthful drafting (typed cited sentences + deterministic verifier) and quoted research

- **Status:** Accepted
- **Date:** 2026-10-17

## Context
Application documents must never contain invented facts (non-negotiable 1). Models, especially
7–9B local ones, invent plausible details. Requirements research reads untrusted web pages that can
contain prompt injection, and different pages can disagree (deadlines, language scores).

## Decision
- **Drafting contract.** The model returns `DraftDocument`: sections of sentences, each typed
  `claim` (about the candidate, must cite profile entry ids), `position` (about the opportunity,
  may cite research finding ids), `intent` (motivation or plans: no facts, no numbers) or
  `placeholder`. JSON-schema structured output where supported, otherwise validate + one repair.
- **Deterministic verifier** (`domain/drafting.verify_draft`). It keeps a claim only if it cites
  existing accepted, non-private entries and every number in it appears as a whole token in those
  entries. Position sentences are checked the same way against findings plus the listing.
  Intent sentences are kept but flagged for the user. Everything removed is reported with a
  reason. Missing required sections become `[[PLACEHOLDER: …]]`. Edits by the user are their
  own text and are not re-verified; placeholders are recounted.
- **Academic CV is assembled, not generated.** Every line comes from one accepted entry, so no
  model is used.
- **Research is rule-based and quoted.** `rules_v1` extracts deadlines, degree, language tests,
  documents, funding and people. Each finding stores a verbatim quote (checked to be a substring of
  the stored source text), its source, a confidence and freshness (stale after 30 days).
  Disagreements across sources are marked `conflict`, never resolved silently.
- **Fetching** goes through `SafeFetcher`. It connects only to the IP address it checked at connect
  time (custom httpcore network backend, so no DNS-rebinding window), re-checks every redirect,
  respects robots.txt, and enforces size, time and type caps. Reserved `.example` demo hosts are
  never fetched; bundled, labelled demo pages are used instead.
- **Consent.** Drafting with a model whose data leaves the device requires an approval that lists
  the entries to be sent. Rejecting it sends nothing and creates nothing.

## Alternatives
- Free-text generation with post-hoc fact extraction: unreliable for small models and hard to
  explain to users.
- LLM-based research extraction: deferred. It would use the same quote-must-be-substring check.

## Consequences
- Drafts are deliberately conservative and contain placeholders; users finish them.
- A sentence that combines a claim and a position must be split by the model, or it is removed.
- Number checks are lexical. "two years" vs "2 years" isn't normalized, so the conservative
  outcome is removal.
