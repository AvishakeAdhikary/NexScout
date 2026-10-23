# Changelog

Releases are created automatically from `main` after CI passes (`.github/workflows/release.yml`).
Each one bumps the **minor** version and lists its commits in the GitHub release notes. This
file summarizes the larger milestones.

## v2.10.0
- **Contact details** (Profile → Contact details): name, email, phone, city, country, and an
  optional address.
  - Found in your CV and suggested. Nothing is saved until you press Save.
  - Used in resumes, CVs and letter sign-offs, and to fill application forms: first and last
    name, phone, city, country, location, postal code and profile links.
  - Never sent to an AI model: NexScout adds them after the writing.
- **Applying works without the PDF dance.** "Fill in the form" first fills in what you already
  told NexScout, makes any missing PDF and checks it. Only then does it open the page.
  - The app used to refuse with "Create the PDF files for the chosen documents first", even
    though the application page had no way to make them.
  - If a document still needs something only you can write, the run says which document and
    what is missing.
- **Documents where you need them.** On the application page, the position page and the
  Documents page, every document has **Fill in my details**, **Make PDF**, **Download PDF** and
  **Delete**. The application page shows the position's own documents first.
- **Fixed: deleting a document that had a PDF failed** (an internal format code was taken for a
  file name). Deleting a document now also takes it off applications.
- Developers: Prettier for the web and desktop apps (`npm run format`; `npm run lint` checks
  it), with `eslint-config-prettier`. Both apps were reformatted once.

## v2.9.0
- **M18: your profile is portable and read properly.**
  - **Export profile and Import a profile.** One case is moved as a `.nexscout` file: every
    entry, the mind map layout, snapshots, relationships, answers and documents. Import always
    creates a new case and checks the file thoroughly. Operators also get the CLI commands
    `nexscout export-case`, `import-case` and `reread-documents`.
  - **CV reader v2.**
    - Markdown CVs and their PDF exports read the same: no stray `**`, and no "JavaScript
      (React.js" split in two.
    - Projects come with clean names and are linked to the job they were done in.
    - Spoken languages are read with their level.
    - Publications are split into title, authors and venue.
    - Links and titles that a PDF wrapped onto the next line are joined back together.
    - An entry you already have, or rejected, is never added again. That holds even after you
      edited it, or wrote the employer's full legal name ("… Private Limited").
    - A project links to the job or degree it was done in, including your own accepted
      version of that job.
  - **Leftover suggestions:** when you delete a file but keep its unreviewed suggestions, the
    Profile page offers to remove them in one click.
  - **Letters of recommendation** add the recommender as a private reference: name, position,
    organisation, contact, and how they know you.
  - **Read again** on a document replaces only unreviewed suggestions.
  - **"Part of" links** between entries: a project in a job, a certificate from a study. They
    show on the mind map and in drafts.
  - **Profile:** tick or select-all entries to accept, reject, delete or make them private in
    bulk.
  - **Mind map:** Auto-arrange (left-to-right or top-to-bottom), and delete snapshots.
  - **Documents:** drag-and-drop upload, several files at once.

## v2.7.0
- **Skip the model's thinking** (Settings → AI models, OpenAI-compatible servers). Reasoning
  models on NVIDIA NIM or vLLM can answer without thinking first. In the real run, Nemotron
  spent its whole answer budget reasoning; with this setting it used 0 reasoning tokens and the
  answer was complete. The setting is off by default, because servers that don't know it
  (OpenAI's own API) reject the request.
- AI drafts use the model's own answer limit (Settings → AI models → Edit), up to half its
  context window. The fixed cap of 8192 meant raising the limit did nothing, though the
  message said to raise it.

## v2.6.0
- AI drafts allow up to about 9 minutes for a long answer from a model that thinks first
  (they timed out at 2 minutes in the real run). When the model server is slow or unreachable,
  the run says so ("The model server didn't answer within 546 s"); it no longer says
  "a database or network hiccup".

## v2.5.0
- **M17, continued.**
  - The desktop app and the Easy zip no longer take over each other's Docker stack. That
    would have left saved keys unreadable. Each now refuses, with a message saying which
    install is running.
  - "Research and prepare" on job postings now lists what the posting says about
    experience, visas, work rights, languages and relocation, each quoting its sentence.
  - A language written as "a plus", "nice to have" or "von Vorteil" is no longer treated as
    required.
  - **AI-written documents work with reasoning models.**
    - Drafts may use up to 8192 answer tokens, within the model's limit. They were capped at
      2048, and a thinking model (NVIDIA Nemotron) ran out of room before writing its answer.
    - A cut-off answer now says how to fix it ("raise Longest answer"). It is no longer
      reported as "didn't have the expected structure".
    - Tokens used by failed attempts are recorded.
    - New AI models default to a 4096-token answer limit.
- **Verified for real:**
  - The installed 2.3.0 Windows app updated itself to 2.4.0. It downloaded 971 KB
    (differential), installed on quit and cleaned the updater cache.
  - "Update NexScout" took a 2.3.0 zip install to 2.4.0: checksum verified, keys kept, old
    images removed.

## v2.4.0
- **M17: fixes from a real run.** One person's real CV and preferences went through the
  released v2.3.0 stack against 180 live sources.
  - Matching reads the posting text: skills mentioned, years asked for (quoted), "Senior"
    titles, the language the posting is written in, and postdocs needing a doctorate. Scores
    now separate postings: on that run, the spread doubled.
  - Refused visa sponsorship and a language you don't list are hard no's in every mode.
  - Sites that forbid automation (for example Duunitori) are refused before any request when
    added by URL or imported.
  - Imports respect the 300-source limit.
  - "Lunds universitet" and "Lund University" (and "X AB"/"X Oy") count as one employer.
    Mind-map positions saved for such organisations are reset once.
  - The catalog is verified live when it is built: dead boards are removed with the reason,
    duplicates are merged, and it adds 8 more Swedish universities and Tampere University.
  - Feeds named in the query string (`?format=rss`) are recognised.

## v2.3.0
- **M16: edit AI models and automatic updates.**
  - Edit an AI model in place (Settings → AI models → Edit). Change its name, model, address,
    limits or key without removing and adding it again. The key is never sent to a changed
    server address unless it's entered again.
  - The Windows app updates itself from GitHub releases: it checks every 6 hours, downloads
    in the background, asks before restarting, and cleans up downloaded installers.
  - Easy mode removes old NexScout images after updating.
  - The Easy zip has **Update NexScout** scripts, with checksums verified against
    `SHA256SUMS.txt`.
  - An "update available" notice in the web app (`GET /api/v1/version`).

## v2.2.0
- **M15: real sources.**
  - Demo data is gone from shipped builds. NexScout now reads real positions through 32
    providers: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Personio, Teamtailor and
    more, EU job boards such as Work in Finland, Arbeitsagentur, Platsbanken and The Hub, and
    Swedish university feeds.
  - A catalog of 168 sources, built from career-ops (MIT) plus EU, Finnish and academic
    additions.
  - Add any careers page by URL, with auto-detection, or import a career-ops `portals.yml`.
    Each source shows its health and can be checked on demand.
  - Sites that forbid automation are listed as manual only, with the reason.
- **Countries.** Every ISO country plus groups (EU, Nordics, Europe, …), as include and exclude
  lists in preferences and the autopilot.
- **Eligibility signals.** Visa sponsorship, required work rights, required languages and
  funding are read from each posting and explained.
- **Budget.** An upfront-cost limit in your own currency, checked against stated fees with the
  ECB daily rates.
- **Reminders fall due on your own day.** Your time zone is taken from your browser.
- **M14: production defaults and error sweep.**
  - Shipped builds run in production mode, with secure cookies on https and no API docs.
  - The web app finds the API at runtime, which fixes desktop local mode.
  - Errors are shown as plain messages with a reference, never Python internals.
  - Every route is crawled in E2E for page errors, console errors and API 5xx, in both dev and
    production builds.

## v2.0.0 (first automatic release)
- **M13: releases and easy install.**
  - An automatic minor-version release on every green `main` push: GHCR images, the Windows
    installer and the easy bundle.
  - Easy mode in the desktop app (NexScout's own Docker stack, with secrets in the OS keychain).
  - Double-click start scripts for Windows, macOS and Linux.
  - A Getting started checklist, a non-technical user guide, and a user-first README.
- **M12: human-in-the-loop autopilot.**
  - Consented standing policies, decided by deterministic rules with reasons.
  - Scheduled discover → research → documents → fill → submit, or ask for approval.
  - An answer bank: questions are asked once and answers reused; nothing is guessed.
  - Manual-only sites, robots.txt and pacing.
  - Assisted mode for CAPTCHAs and sign-ins.
  - A kill switch (including STOP from chat) and a daily digest.
- **M11: notification channels.**
  - Telegram, Discord, WhatsApp Cloud API, Slack, email and signed webhooks, through official
    APIs.
  - Pairing, identity-bound single-use buttons, answers by reply.
  - A durable outbox with retries, dead letters, a circuit breaker and quiet hours.
- Regional document formats with posting compliance checks.
- **M0–M10:** profile and ingestion, mind map, discovery and dedup, the durable agent runtime,
  PhD and job workflows, browser automation with approvals, tracking, the desktop app, the MCP
  server, and hardening. See `docs/ROADMAP.md`.
