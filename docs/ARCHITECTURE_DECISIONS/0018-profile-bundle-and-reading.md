# ADR-0018: Portable profile bundle, CV reader v2, letters, links between entries

- **Status:** accepted (M18, 2026-10-23)
- **Context:** A user spent hours building a profile and mind map and had no way to move it or
  to restart without retyping. Their real CV produced `** Python`, "JavaScript (React.js" plus
  "Angular)", and nonsense entries they deleted one by one. Two recommendation letters produced
  nothing. Projects couldn't be tied to the job they were done in, so drafts couldn't say "built
  at <employer>".

## Decision
1. **Bundle format `nexscout-profile/1`** (`application/profile_bundle.py`).
   - A zip with `profile.json` and, optionally, the original documents under
     `documents/<n>/<file>`.
   - It contains: the case, preferences, every entry (any review state) with its evidence,
     relationships, links, mind-map overrides, snapshots, the answer bank, and document text.
   - It never contains secrets, AI providers, applications, runs, notifications or sources.
   - `GET /cases/{id}/export?documents=`. `POST /cases/import` always creates a **new** case
     (name collision → "X (imported)").
   - Operator CLI: `nexscout export-case | import-case | reread-documents`.
2. **Import is hostile-input safe.**
   - Limits: 100 MB file, 300 MB unpacked, 500 parts.
   - No absolute or `..` paths and no drive letters.
   - `profile.json` is at most 50 MB.
   - Every entry goes through `validate_fact_data`, every document through `sniff`, preferences
     through the Preferences model, relationships and links through their own use cases.
   - All ids are remapped: entries, documents, `fact:<id>` node keys, snapshot rows and
     `related_fact_ids`.
   - Meta keys are allow-listed.
   - A newer format is refused with "update NexScout". Unknown parts and bad entries are skipped
     and reported, never trusted.
   - Imported documents keep `origin='uploaded'`; the audit log records `case.imported`.
3. **CV reader v2** (`domain/cv_heuristics.py`, `heuristic_v2`).
   - It works on logical lines: wrapped PDF and Markdown lines are joined to their bullet or
     header.
   - Entries start at `###`, after a blank line, or at a header run, meaning 1–2 lines followed
     by a date line. A two-line header must not start with a line that ends a sentence, so a
     wrapped bullet's last line isn't taken as a header.
   - Field values are cleaned of Markdown and ligatures. Evidence spans stay on the original
     text, so quotes remain verbatim.
   - **Skill lists:**
     - split only at the top level;
     - `X (A, B)` becomes X, A and B;
     - an acronym stays with its name;
     - a slash splits only between single tokens;
     - implausible fragments are dropped.
   - **Locations** end at a country name, using the ISO data.
   - **Projects:** `Name -- tagline` gives the name, technologies come from `Tech:` lines, and
     the URL from links or bare GitHub paths.
   - **Spoken languages** become skills with a level.
   - **No duplicates:** entries the case already has, in any review state, are skipped. Re-reading
     never brings back what the user rejected.
     - "The same entry" is decided by `identity_keys`: the same employer (legal suffixes such as
       "Private Limited" ignored) and start, the same institution and start, the same name, or the
       same DOI or title.
     - Keys are also taken from the wording the user edited away (`meta.original_data`).
   - **Publications** are split into authors, title and venue. The author list ends at the first
     full stop after a surname.
   - **PDF wraps:** a link wrapped onto the next line is joined back together, and so is a word
     broken at a hyphen. A title separated from its date line by a blank line stays with it.
4. **Recommendation letters** (`domain/letters.py`).
   - A letter yields one **pending, private reference**: name, position, organization, contact
     and the letter's own words for the relationship.
   - These are read from the signature block (after "Sincerely", or the last block of lines)
     and from the letter body (after the salutation, before the signature).
   - Nothing in a letter becomes a claim about the candidate.
5. **Links between entries** (`related_fact_ids` on every entry, at most 5).
   - Targets are restricted to employment, education, research, volunteer, leadership or
     membership entries in the same case.
   - Deleting an entry removes it from other entries' links.
   - Links show as `part_of` edges on the mind map and in the ELK layout. Drafting sees them as
     readable `part_of` labels.
   - The reader links a project to the job or degree its date line names, or to the job whose
     description names the project. With two degrees at one university, it picks the degree
     whose dates contain the project.
   - When the case already has that job (for example accepted and edited), the link points to
     the existing entry.
6. **Re-read** (`POST /documents/{id}/reread`). It replaces only that document's pending,
   unedited entries.
   - A user can delete a file but keep its suggestions. Those suggestions are never removed
     automatically. The Profile page offers to remove them (bulk delete, after the user confirms).

## Consequences
- A profile can be backed up, moved to another computer, or restored next to the original.
- Old bundles keep importing: the format number only changes with an explicit migration step
  in `_open`.
- The reader is still rule-based. Unusual layouts fall back to an `other` entry with a warning,
  and "Read with AI" (M21) is the next step for those.
