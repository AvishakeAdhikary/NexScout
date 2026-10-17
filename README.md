<p align="center"><img src="apps/web/src/app/icon.svg" width="72" alt="NexScout telescope logo"></p>

# NexScout

**Your truthful application assistant for PhD positions and jobs.** NexScout reads your CV,
finds positions that fit you, researches them with sources, and writes your documents from
facts you confirmed. It can fill in and submit applications for you, and it asks you on your
phone whenever it needs a decision or an answer. It never invents anything about you, and
never does anything consequential without your permission.

## Get started (no technical knowledge needed)
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free) and open it
   once.
2. Download NexScout from [**Releases**](https://github.com/AvishakeAdhikary/NexScout/releases/latest):
   - **Windows:** `NexScout-Setup-<version>.exe`, then choose **Easy** when it opens.
   - **Windows, Mac or Linux:** `nexscout-easy-<version>.zip`. Unzip it and double-click
     **Start NexScout** in the `easy` folder.
3. Create your account and follow **Getting started**.

The [user guide](docs/USER_GUIDE.md) explains everything step by step, including phone
notifications, the autopilot, and how NexScout keeps you out of trouble online.

## What it does
- **Profile from your CV** (PDF, Word, Markdown). Every entry shows its source, and nothing is
  used until you confirm it.
- **Finds PhD positions and jobs**, merges duplicates, and explains each match, including what
  you're missing.
- **Researches each position**: requirements, deadlines and supervisors, each quoted from its
  source.
- **Writes truthful documents**: statement of purpose, research proposal, CV, resume, cover
  letter, emails.
  - Every claim cites your confirmed facts. Anything unknown becomes a placeholder or a
    question.
  - The format follows the country of the position (for example a Lebenslauf on A4, US Letter,
    or Europass).
- **Applies for you.** It fills in the form, shows you everything, and submits once, after your
  approval or within autopilot rules you agreed to.
  - It stops at CAPTCHAs and sign-ins. Assisted mode lets you solve them in a window it opens.
- **Phone notifications with buttons**: Telegram, Discord, WhatsApp (official Cloud API),
  Slack, email or a webhook. Approve, reject, or answer by replying.
- **Autopilot.** It works on a schedule within your limits and asks instead of guessing.
  Your answers are saved and reused. Send **STOP** from your phone to stop everything.
- **Stays within the rules.** It never automates sites that forbid it (LinkedIn, Indeed,
  Glassdoor and others), respects robots.txt, goes slowly, and uses official messaging APIs.
- **Your data stays yours.** It runs on your computer, encrypts your saved keys, and lets you
  export or delete everything.
- **Bring your own AI**: OpenAI, Anthropic, Gemini, or free local models (Ollama, LM Studio).
  NexScout asks before data leaves your computer.

> **Honest status:** everything above is implemented and tested. The test evidence is in
> [docs/ROADMAP.md](docs/ROADMAP.md). The built-in sources and the application site used in
> tests are **labelled demo data**. Real AI providers and real chat apps are supported through
> their official APIs but are **not live-verified** in this repository. See
> [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Releases
Every change that passes all checks on `main` is released automatically with the next
**minor** version (`v2.0.0`, `v2.1.0`, …). Each release includes Docker images, the Windows
installer and the easy bundle. See [CHANGELOG.md](CHANGELOG.md).

## For developers
```bash
cp .env.example .env
docker compose up -d postgres
cd backend && uv sync && uv run nexscout migrate
uv run nexscout serve --reload      # API  :8000
uv run nexscout worker              # background worker (required)
cd ../apps/web && npm install && npm run dev   # web :3000
```
Everything in containers, built from source: `docker compose --profile full up -d --build`.

- Setup and commands: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- Architecture and decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
  [docs/ARCHITECTURE_DECISIONS/](docs/ARCHITECTURE_DECISIONS/)
- Security model: [docs/SECURITY.md](docs/SECURITY.md)
- Operations (backup and restore, deploy, desktop, releases): [docs/OPERATIONS.md](docs/OPERATIONS.md)
- Contributor and agent rules: [AGENTS.md](AGENTS.md)

## License
[AGPL-3.0-only](LICENSE), carried over from NexScout v1. The previous implementation is
preserved in this repository's history and under the tag `v1-legacy`.
