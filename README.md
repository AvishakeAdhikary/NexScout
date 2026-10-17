<p align="center"><img src="apps/web/src/app/icon.svg" width="72" alt="NexScout telescope logo"></p>

# NexScout

NexScout helps people turn their real achievements into truthful PhD and job applications.
It researches opportunities with cited sources, drafts application materials grounded in your
confirmed profile, and never submits or sends anything without your approval.

> **Status:** all planned milestones (M0–M10) are implemented and tested on Windows with
> Docker Postgres. Data sources and the application site are **labelled demo fixtures**, and
> real AI providers are supported but **not live-verified**. See
> [docs/ROADMAP.md](docs/ROADMAP.md) for the evidence and
> [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for what doesn't work.

## What it does
- **Profile from your documents.** Upload a CV (PDF, DOCX, Markdown). Entries are extracted with
  verbatim source quotes, and nothing is used until you confirm it.
- **Evidence-linked mind map** of your profile, with a list view, and manual edits that survive
  regeneration.
- **PhD and job discovery** from configurable sources: duplicates are merged, and every fit
  estimate is explained, including gaps (strict or flexible experience mode).
- **Position research:** requirements, deadlines, documents and supervisors, each quoted from
  its source. Conflicting sources are flagged.
- **Truthful drafting:** SOP, research proposal, inquiry email, cover letter and referral
  request. Every claim must cite your confirmed entries, and missing details become
  `[[PLACEHOLDER: …]]`. CVs and resumes are assembled without AI. Output is PDF and Word,
  validated.
- **Applications:** the browser fills the form and shows you everything, then submits **once**
  after your approval. It stops at CAPTCHAs and logins, and marks unconfirmed submissions as
  uncertain.
- **Durable agents:** workflows survive crashes and restarts, with pause, resume, cancel, retry
  and approvals, and a live activity view.
- **Tracking:** reminders, in-app notifications, a dashboard, bulk changes, CSV export, and an
  assistant that routes requests to the same tools.
- **Bring your own AI:** OpenAI-compatible (OpenAI, Ollama, LM Studio), Anthropic and Gemini, or
  a labelled mock. You consent before data leaves your device.
- **Integrations:** a read-only MCP server (`nexscout mcp`) and a sandboxed Electron desktop
  shell.

## Quick start (development)
```bash
cp .env.example .env
docker compose up -d postgres
cd backend && uv sync && uv run nexscout migrate
uv run nexscout serve --reload      # API  :8000
uv run nexscout worker              # background worker (required)
cd ../apps/web && npm install && npm run dev   # web :3000 (dark mode by default)
```
Everything in containers: `docker compose --profile full up -d --build`.

## Docs
- Developer setup and commands: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Architecture and decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
  [docs/ARCHITECTURE_DECISIONS/](docs/ARCHITECTURE_DECISIONS/)
- Security model: [docs/SECURITY.md](docs/SECURITY.md)
- Operations (backup and restore, deploy, desktop): [docs/OPERATIONS.md](docs/OPERATIONS.md)
- Contributor and agent rules: [AGENTS.md](AGENTS.md)

## License
[AGPL-3.0-only](LICENSE), carried over from NexScout v1. The previous implementation is preserved
in this repository's history and under the tag `v1-legacy`.
