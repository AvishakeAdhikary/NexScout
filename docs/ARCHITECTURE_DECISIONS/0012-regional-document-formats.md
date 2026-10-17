# ADR-0012: Regional document formats and posting compliance checks

- **Status:** Accepted
- **Date:** 2026-10-17

## Context
Applications get rejected for format reasons that have nothing to do with the candidate. A US
resume runs to three pages. A German CV doesn't lead with its dates. A statement exceeds the
posting's "max. 2 pages". The wrong paper size is used. The same truthful content has to be
shaped by where the position is, and checked against what the posting itself asks for.

## Decision
- **Format profiles** (`domain/formats.py`):
  - North American (US Letter), UK/Ireland, German-speaking *Lebenslauf* (date-first, ends with
    place/date placeholders), European (Europass-style order), Australia/New Zealand (referees),
    and an **international fallback**.
  - Each profile holds conventional page limits, date style, contact hint and notes.
  - They are labelled as conventions, not official rules.
- **Resolution:**
  1. The user's explicit choice.
  2. The opportunity's `location_country`.
  3. International, with an honest reason (location unknown, or no profile for that country).
- **Assembly:**
  - CVs and resumes are assembled from accepted entries in the profile's style.
  - Model-drafted documents get the profile's length and conventions in the prompt.
  - The chosen format, with its reason, is stored with every version; edits keep it.
- **Rendering** uses the profile's paper size (A4 or US Letter) in both PDF and DOCX.
- **Compliance** (`domain/compliance.py`) runs after every render.
  - **Posting requirements** from research findings (page or word limits stated for this kind of
    document) are *blocking*. Unfilled placeholders are blocking too.
  - **Convention** limits are *warnings*.
  - The browser workflow refuses to upload a document with blocking failures.
- **Never added on the user's behalf:** photos, date of birth, marital status, nationality,
  declarations or signatures. Where a region expects place, date or referees, NexScout inserts
  placeholders.

## Consequences
- Headings are in English. Writing in the posting's language (e.g. German) isn't automated;
  the notes say when it's usually expected.
- Countries with standard forms (e.g. Japan's *rirekisho*) fall back to the international format
  with a note to check the employer's instructions.
- Posting limits are found only when research quoted them. Unquoted requirements can't be
  checked, so the user still has to read the posting.
