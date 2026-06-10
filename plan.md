# NexScout — Implementation Plan (Standalone)

> **NexScout** is an always-on, autonomous job-application agent. It discovers jobs across the web, scores them against the user's profile, tailors a LaTeX-rendered resume (and cover letter when required) per application, and submits the application through an undetected Chrome driver with mandatory CAPTCHA solving. It runs continuously inside an OpenClaw / NemoClaw heartbeat, exposes a FastAPI + HTMX web UI for the user, and stores every application's full bundle (PDFs, screenshots, transcript) on disk.

This document is the **sole specification** for the project. Everything needed to build NexScout from scratch — prompts, constants, schemas, algorithms, file layout, registries — is contained inline. No external repository or codebase is required as reference.

License: **AGPL-3.0-only**. Python **3.11+**.

---

## Table of Contents

1. Mission & Definition of Done
2. OpenClaw + NemoClaw background
3. Profile YAML schema (single source of truth for the user)
4. Repository layout
5. SQLite schema (one source-of-truth column registry)
6. LLM router architecture
7. Pipeline stages overview
8. Stage 1 — Discovery (JobSpy, Workday, SmartExtract, WebSearch)
9. Stage 2 — Enrichment (3-tier cascade)
10. Stage 3 — Scoring
11. Stage 4 — Tailoring (with LaTeX render)
12. Stage 5 — Cover Letter
13. Stage 6 — Application (native agent, mandatory CAPTCHA)
14. Validator constants (banned words, leak phrases, fabrication watchlist)
15. CAPTCHA detect/solve specification
16. Per-application bundle layout
17. Web UI specification
18. OpenClaw skill + memory contract
19. CLI specification
20. Docker / docker-compose
21. Workday employer registry (ship as default)
22. Direct career-site registry (ship as default)
23. Code quality requirements
24. Dependencies
25. Roadmap (milestones)
26. Reference prompt for a fresh session

---

## 1. Mission & Definition of Done

**Mission.** Let a job-seeker fill out one YAML profile, then have an autonomous agent — running on a heartbeat — discover relevant jobs anywhere on the web, write a tailored ATS-friendly LaTeX resume and (only when the form requires one) a tailored cover letter for each job, and submit the application using an undetected browser. The agent must never lie about the candidate's facts and must escalate to the user only when it lacks an answer that genuinely cannot be derived from the profile.

**Definition of Done (v0.1.0).** A fresh contributor on a clean machine runs:

```bash
git clone <repo>
cd nexscout
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
nexscout init                              # YAML wizard fills ~/.nexscout/profile.yaml
export CAPTCHA_API_KEY=...
nexscout doctor                            # all green
nexscout run                               # discover → enrich → score → tailor → cover → render
nexscout web &                             # http://127.0.0.1:8765
nexscout apply --workers 2                 # submit applications
# Optional always-on mode:
openclaw skill install ./src/nexscout/openclaw/manifest.toml
```

…and observes (a) `ruff check src/` returns 0, (b) `pytest` is green, (c) the web UI lists applied jobs with their tailored PDFs.

---

## 2. OpenClaw + NemoClaw background (for the implementer)

- **OpenClaw** is an open-source, MIT-licensed, local-first personal-AI agent platform. It stores memory as plain Markdown files under `~/.openclaw/memory/`. It runs a background **heartbeat daemon** (systemd on Linux, LaunchAgent on macOS, Task Scheduler on Windows) that wakes on a configurable interval (default 30 minutes) and invokes registered "skills". It speaks to the user via channels (Slack, Discord, WhatsApp, Telegram, iMessage, Signal, Matrix, WebChat, etc.). A skill is registered through a manifest TOML file and is invoked either by the heartbeat or by a slash-command from the channel.
- **NemoClaw** is NVIDIA's reference stack that runs OpenClaw inside the **OpenShell** sandbox. The sandbox uses Landlock + seccomp + a network namespace to confine the agent to `/sandbox` and `/tmp` and to police outbound network access. Inference is routed via NVIDIA cloud or a local NIM endpoint. From NexScout's point of view, NemoClaw is just "OpenClaw with stricter filesystem and network policies" — no code change is required, only the `~/.nexscout/` directory must be mounted into `/sandbox/nexscout/`.

NexScout supports two run modes:

1. **Hosted-agent mode (recommended).** A `nexscout` skill is registered with OpenClaw via a manifest. The heartbeat calls `nexscout tick`, which performs **one bounded unit of work** (e.g. enrich up to N jobs, score up to M, apply to up to K) and returns. All persistent state lives in `~/.nexscout/`.
2. **Standalone mode.** Plain `nexscout run --continuous` loop. No heartbeat. Same code paths.

Skills NexScout registers:

| Slash-command | Action |
|---------------|--------|
| `/nexscout status` | Pipeline stats + last 5 events |
| `/nexscout apply <url>` | One-shot apply to a specific URL |
| `/nexscout pause` / `/nexscout resume` | Toggle the continuous loop |
| `/nexscout question` | List open clarifying questions |
| `/nexscout answer "<q>" "<a>"` | Answer a question; persisted to memory |

**Memory contract.** When the apply agent needs an answer that is not in the profile or in `learned-answers.md`, it (a) queues the question into the SQLite `pending_questions` table, (b) marks the job `paused_for_question`, (c) on the next heartbeat OpenClaw delivers the question to the user via the active channel. On `/nexscout answer`, NexScout writes the Q&A pair to `learned-answers.md` and stores the answer in the job row's `profile_addendum_json` column for traceability. On the next tick the job resumes.

Memory file layout:

```
~/.openclaw/memory/nexscout/
├── profile.yaml              # symlink → ~/.nexscout/profile.yaml
├── learned-answers.md        # harvested Q&A pairs (no secrets)
├── learned-employers.md      # facts about specific employers
├── do-not-ask-again.md       # questions the user silenced
└── feedback.md               # user corrections ("Don't apply to X")
```

---

## 3. Profile YAML Schema

The **only** file the user fills out. Path: `~/.nexscout/profile.yaml`. Editable through the web UI's `/profile` page and through `nexscout init`. Keys are deliberately short to save LLM tokens.

```yaml
# NexScout master profile — fill once; every application is tailored from this.

meta:
  v: 1                          # schema version
  locale: en_US
  updated: 2026-05-20

me:
  legal: Jane Q. Public          # legal name
  pref: Jane                     # preferred / display name
  email: jane@example.com
  phone: "+1-415-555-0100"
  city: San Francisco
  region: CA
  country: USA
  postcode: "94110"
  address: "123 Main St"         # optional
  links:
    li: linkedin.com/in/janepublic
    gh: github.com/janepublic
    web: jane.dev
    portfolio: jane.dev/work

auth:
  authorized: yes
  sponsor: no                   # require sponsorship?
  permit: USC                   # USC | PR | H1B | OWP | TN | OTHER

pay:
  expect: 165000
  range: [150000, 200000]
  currency: USD
  hourly_note: "divide annual by 2080"

avail:
  start: "Immediately"
  fulltime: yes
  contract: no
  notice: 2w

exp:
  years: 7
  edu: "BSc Computer Science"
  current_title: "Senior Software Engineer"
  target_titles:
    - Staff Engineer
    - Senior Backend Engineer
    - Principal Engineer

# Skills boundary — anything the tailor mentions outside this set = fabrication.
skills:
  lang:   [Python, TypeScript, Go, SQL, Bash]
  fw:     [FastAPI, React, Django, Next.js]
  infra:  [Docker, Kubernetes, AWS, Terraform, GitHub Actions]
  data:   [Postgres, Redis, Kafka, ClickHouse]
  tools:  [Git, Linux, Vim]

# Real facts — preserved verbatim; tailor cannot rename or rewrite numbers.
facts:
  companies: [Acme Corp, Globex]
  projects:
    - "Search Indexer (50M docs/day)"
    - "Auth Gateway"
  school: "State University"
  metrics:
    - "reduced p99 by 38%"
    - "10M MAU"
    - "saved $2.1M/yr"

eeo:
  gender: decline
  race: decline
  veteran: not-protected
  disability: decline

search:
  queries:
    - {q: "staff engineer",   tier: 1}
    - {q: "senior backend",   tier: 1}
    - {q: "platform engineer", tier: 2}
    - {q: "infra engineer",   tier: 3}
  locations:
    - {label: "Bay Area",  q: "San Francisco, CA", remote: false}
    - {label: "Remote US", q: "Remote",            remote: true}
  exclude_titles: [intern, "vp", chief, "co-op", clearance]
  hours_old: 72
  min_score: 7
  boards:
    jobspy: [indeed, linkedin, glassdoor, zip_recruiter, google]
    websearch:
      providers: [tavily, brave, duckduckgo, searxng]
      queries_per_day: 200

llm:
  primary: gemini-2.0-flash
  fallback: ollama:llama3.1:70b
  judge: anthropic:claude-haiku-4-5-20251001
  budgets:
    monthly_usd: 30
    daily_calls: 5000

apply:
  workers: 2
  headless: true
  dry_run: false
  max_attempts: 3
  max_per_run: 0
  permitted_atss: [greenhouse, lever, ashby, workday, taleo, icims, smartrecruiters]

captcha:
  provider: capsolver           # capsolver | 2captcha | anti-captcha
  api_key: "${env:CAPTCHA_API_KEY}"
```

**Loader rules.** `${env:NAME}` is resolved at load time. `meta.v` triggers forward migrations. The loader validates with Pydantic (`Profile` model) and emits human-readable errors. A method `Profile.to_resume_text()` produces a minimal plain-text resume that the scorer/tailor use as the candidate's "base resume" (the user no longer needs a separate `resume.txt`).

---

## 4. Repository Layout

```
NexScout/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE                       # AGPL-3.0
├── .ruff.toml
├── .pre-commit-config.yaml
├── .github/workflows/ci.yml
├── Dockerfile
├── docker-compose.yml
├── src/nexscout/
│   ├── __init__.py               # __version__
│   ├── __main__.py
│   ├── cli.py                    # Typer entry
│   │
│   ├── core/
│   │   ├── config.py             # paths, ensure_dirs, get_chrome_path (cross-platform)
│   │   ├── settings.py           # pydantic-settings, .env loader
│   │   ├── profile.py            # YAML profile model + loader + migrations
│   │   ├── database.py           # SQLite schema, ensure_columns, get_stats
│   │   ├── logging.py            # rich + structured JSON logs
│   │   └── errors.py
│   │
│   ├── llm/
│   │   ├── router.py             # task-aware LLM dispatch + budget
│   │   ├── budget.py             # SQLite-backed ledger
│   │   └── providers/
│   │       ├── base.py
│   │       ├── gemini.py         # OpenAI-compat with native fallback
│   │       ├── openai.py         # OpenAI + Azure
│   │       ├── anthropic.py      # native messages API with prompt-cache
│   │       ├── ollama.py
│   │       ├── lmstudio.py       # OpenAI-compat at :1234/v1
│   │       ├── vllm.py
│   │       └── llamacpp.py
│   │
│   ├── discovery/
│   │   ├── jobspy.py             # Indeed / LinkedIn / Glassdoor / ZipRecruiter / Google
│   │   ├── workday.py            # Workday CXS API
│   │   ├── smartextract.py       # AI-driven scraping (JSON-LD → API → CSS)
│   │   └── websearch.py          # Tavily / Brave / DDG / SearXNG
│   │
│   ├── enrichment/
│   │   └── detail.py             # 3-tier cascade
│   │
│   ├── scoring/
│   │   ├── scorer.py
│   │   ├── tailor.py             # structured JSON + retries + judge
│   │   ├── cover_letter.py
│   │   ├── validator.py          # banned/leak/fabrication checks
│   │   └── render/
│   │       ├── engine.py         # tectonic → latexmk → pdflatex
│   │       ├── latex_filter.py   # latex_escape, currency_fmt, etc.
│   │       └── templates/
│   │           ├── resume_classic.tex.j2
│   │           ├── resume_modern.tex.j2
│   │           └── cover_letter.tex.j2
│   │
│   ├── browser/
│   │   ├── driver.py             # undetected_chromedriver wrapper
│   │   ├── pool.py               # per-worker isolation
│   │   └── stealth.py            # cdc/webdriver/plugins patches
│   │
│   ├── captcha/
│   │   ├── base.py               # CaptchaSolver protocol
│   │   ├── capsolver.py
│   │   ├── twocaptcha.py
│   │   ├── anticaptcha.py
│   │   └── detect.py             # in-page detection script
│   │
│   ├── apply/
│   │   ├── orchestrator.py       # acquire_job, mark_result, worker_loop
│   │   ├── agent.py              # ReAct loop driving the browser
│   │   ├── tools.py              # navigate/click/fill/upload/screenshot/...
│   │   ├── form_filler.py
│   │   ├── policy.py             # safety rules
│   │   ├── result_codes.py
│   │   ├── prompt.py             # the full system-prompt builder
│   │   └── dashboard.py          # Rich live dashboard
│   │
│   ├── agent_backends/
│   │   ├── native.py             # default; uses LLM router + tools
│   │   ├── claude_code.py        # optional shim if user has Claude Code CLI
│   │   └── openai_assistant.py   # optional
│   │
│   ├── openclaw/
│   │   ├── manifest.toml         # skill manifest
│   │   ├── skill.py              # /nexscout slash-command handlers
│   │   ├── memory.py             # markdown reader/writer
│   │   └── tick.py               # bounded-unit-of-work entry
│   │
│   ├── web/
│   │   ├── app.py                # FastAPI
│   │   ├── auth.py               # bcrypt + signed cookie sessions
│   │   ├── routes/
│   │   │   ├── dashboard.py
│   │   │   ├── jobs.py
│   │   │   ├── applications.py
│   │   │   ├── profile.py
│   │   │   ├── questions.py
│   │   │   ├── controls.py
│   │   │   └── api.py
│   │   ├── templates/            # Jinja2 + HTMX
│   │   └── static/               # Tailwind built CSS, htmx.min.js, alpine.min.js
│   │
│   ├── pipeline.py               # streaming orchestrator
│   └── wizard.py                 # interactive init
│
├── tests/{unit,integration,e2e}/
├── examples/split/{profile,settings,credentials}.yaml
└── docs/{architecture,openclaw,latex-templates,developer-guide}.md
```

---

## 5. SQLite Schema

One table `jobs` with all columns from every stage in **one column registry** (`_ALL_COLUMNS: dict[str, str]`). `init_db()` is idempotent (`CREATE TABLE IF NOT EXISTS`). `ensure_columns()` reads `PRAGMA table_info(jobs)` and adds any missing columns via `ALTER TABLE` — forward migrations only, never destructive. Connections are thread-local, WAL mode on, `busy_timeout=10000`.

Columns (name → SQL type):

```
# Discovery
url                       TEXT PRIMARY KEY      # canonical URL
title                     TEXT
salary                    TEXT
description               TEXT                  # short preview, sometimes provided by JobSpy
location                  TEXT
site                      TEXT                  # source label (e.g. RemoteOK, td, indeed)
strategy                  TEXT                  # jobspy | workday_api | json_ld | api_response | css_selectors | websearch
discovered_at             TEXT                  # ISO-8601 UTC
web_search_query          TEXT                  # only set if discovered via websearch

# Enrichment
full_description          TEXT
application_url           TEXT
detail_scraped_at         TEXT
detail_error              TEXT

# Scoring
fit_score                 INTEGER               # 1..10, NULL if not yet scored
score_reasoning           TEXT                  # "<keywords>\n<reasoning>"
scored_at                 TEXT

# Tailoring
tailored_resume_path      TEXT                  # .txt path; .pdf sibling exists when rendered
tailored_at               TEXT
tailor_attempts           INTEGER DEFAULT 0
latex_template            TEXT                  # which template was used

# Cover letter
cover_letter_path         TEXT
cover_letter_at           TEXT
cover_attempts            INTEGER DEFAULT 0
cover_required            INTEGER DEFAULT 0     # detected during enrichment

# Application
applied_at                TEXT
apply_status              TEXT                  # NULL | in_progress | applied | failed | manual | expired | captcha | login_issue | sso_required | paused_for_question
apply_error               TEXT
apply_attempts            INTEGER DEFAULT 0
agent_id                  TEXT                  # worker-<n>
last_attempted_at         TEXT
apply_duration_ms         INTEGER
apply_task_id             TEXT
verification_confidence   TEXT
apply_backend             TEXT                  # native | claude_code | openai_assistant
bundle_dir                TEXT                  # ~/.nexscout/applications/<job_id>/
captcha_solved            INTEGER DEFAULT 0
cost_usd                  REAL DEFAULT 0
profile_addendum_json     TEXT                  # extra answers harvested from user
```

Additional tables:

```
pending_questions (
  id INTEGER PRIMARY KEY,
  job_url TEXT,
  question TEXT,
  asked_at TEXT,
  channel TEXT,          -- slack | discord | webchat | cli | …
  answered_at TEXT,
  answer TEXT
)

events (
  id INTEGER PRIMARY KEY,
  ts TEXT,
  kind TEXT,             -- discover | enrich | score | tailor | apply | error | tick
  payload_json TEXT
)
```

**`get_stats()`** returns counters used by the CLI `status` command and the web dashboard:
`total, by_site, pending_detail, with_description, detail_errors, scored, unscored, score_distribution, tailored, untailored_eligible, tailor_exhausted, with_cover_letter, cover_exhausted, applied, apply_errors, ready_to_apply`.

**Atomic job acquire (apply stage).**

```sql
BEGIN IMMEDIATE;
SELECT url, title, site, application_url, tailored_resume_path,
       fit_score, location, full_description, cover_letter_path
  FROM jobs
 WHERE tailored_resume_path IS NOT NULL
   AND (apply_status IS NULL OR apply_status = 'failed')
   AND (apply_attempts IS NULL OR apply_attempts < ?max_attempts)
   AND fit_score >= ?min_score
   AND site NOT IN (?blocked_sites…)
   AND url NOT LIKE ?blocked_pattern…
 ORDER BY fit_score DESC, url
 LIMIT 1;
-- if row found:
UPDATE jobs
   SET apply_status = 'in_progress', agent_id = ?, last_attempted_at = ?
 WHERE url = ?;
COMMIT;
```

**Permanent-failure classification** (these reasons must not be retried — `apply_attempts := 99`):

```
expired, captcha, login_issue,
not_eligible_location, not_eligible_salary,
already_applied, account_required,
not_a_job_application, unsafe_permissions,
unsafe_verification, sso_required,
site_blocked, cloudflare_blocked, blocked_by_cloudflare
# also: any reason that starts with site_blocked / cloudflare / blocked_by
```

---

## 6. LLM Router

```python
class LLMRouter:
    def __init__(self, profile: Profile, budget: BudgetLedger): ...
    def ask(self, task: Task, messages: list[dict], **kw) -> str:
        provider = self._select(task)                      # primary | fallback | judge
        if not self.budget.allow(provider, est_tokens=kw.get("max_tokens", 2048)):
            provider = self._fallback(task)
        return provider.chat(messages, **kw)
```

`task` is one of: `discover`, `enrich`, `score`, `tailor`, `judge`, `cover`, `apply`.

**Providers.** All implement a common `Provider.chat(messages, temperature, max_tokens) -> str` interface.

- **Gemini.** Start on the OpenAI-compat layer at `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`. On HTTP 403 (which happens for preview / experimental models that aren't exposed via compat), automatically switch to the native API: `POST https://generativelanguage.googleapis.com/v1beta/models/<model>:generateContent?key=<API_KEY>` with body `{"contents":[…], "systemInstruction":{"parts":[…]}, "generationConfig":{"temperature":t,"maxOutputTokens":m}}`. Convert OpenAI message roles: `assistant → model`. Cache the "native API works for this model" bit for the lifetime of the process.
- **OpenAI.** Standard `/v1/chat/completions`. Allow base-URL override for Azure OpenAI.
- **Anthropic.** Native `/v1/messages` API. Set `anthropic-beta: prompt-caching-2024-07-31` and include `"cache_control": {"type": "ephemeral"}` on the system block.
- **Ollama.** `POST http://localhost:11434/api/chat`.
- **LM Studio.** OpenAI-compat at `http://localhost:1234/v1`.
- **vLLM / llama.cpp.** OpenAI-compat at user-configured URL.

**Retry policy.** 5 attempts with exponential backoff (base 10s, cap 60s). On HTTP 429/503, honour `Retry-After` / `X-RateLimit-Reset-Requests` headers if present. On timeouts, same backoff. **Qwen optimisation:** if the model name contains "qwen", prepend `/no_think\n` to the first user message to suppress chain-of-thought tokens.

**Budget ledger.** A separate SQLite at `~/.nexscout/budget.sqlite` with columns `provider, day, month, input_tokens, output_tokens, cost_usd, calls`. `allow()` blocks calls that would push past `profile.llm.budgets.monthly_usd` or `daily_calls`.

**Task → provider defaults:**

| task | primary | fallback | judge override |
|------|---------|----------|----------------|
| discover | primary | fallback | — |
| enrich | primary | fallback | — |
| score | primary | fallback | — |
| tailor | primary | fallback | — |
| judge | judge | primary | profile.llm.judge |
| cover | primary | fallback | — |
| apply | primary | fallback | — |

---

## 7. Pipeline Stages — Overview

`nexscout run [stages…]` runs these stages. Stages: `discover, enrich, score, tailor, cover, render`. `all` runs them all. `--stream` runs them concurrently, each polling the DB for upstream work until upstream is done and its own queue is empty (uses `threading.Event` per-stage).

Upstream relationships:

```
discover → enrich → score → tailor → cover → render
```

A streaming-stage worker (for any non-`discover` stage) loops:

```python
while not stop:
    pending = COUNT(*) FROM jobs WHERE <stage's pending predicate>
    if pending > 0:
        run_one_batch()
    else:
        if upstream_done.is_set(): break
        stop.wait(STREAM_POLL_INTERVAL)  # default 10s
done.set()
```

`discover` runs once per tick (the sub-engines do their own full crawl).

---

## 8. Stage 1 — Discovery

Four engines run on each tick. Each writes to `jobs` via `INSERT … ON CONFLICT(url) DO NOTHING`, returning `(new_count, duplicate_count)`.

### 8.1 JobSpy engine

Uses `python-jobspy` (installed via `pip install --no-deps python-jobspy` due to its strict numpy pin; runtime deps are installed separately).

For each `(query, location) ∈ profile.search.queries × profile.search.locations`:

1. Build kwargs:
   ```python
   {
     "site_name": [boards minus glassdoor],
     "search_term": query,
     "location": location.q,
     "results_wanted": profile.search.boards.jobspy_results_per_site or 100,
     "hours_old": profile.search.hours_old,
     "description_format": "markdown",
     "country_indeed": "usa",       # or derived
     "is_remote": location.remote,
   }
   ```
2. Glassdoor needs a simplified location (`location.split(',')[0]`); run it as a separate scrape and concat DataFrames.
3. If `linkedin` is in the boards list, add `"linkedin_fetch_description": True`.
4. Retry transient failures up to 2 times: error string contains `timeout|429|proxy|connection|reset|refused`. Backoff `5 * (attempt+1)` seconds.
5. Apply location filter: accept jobs whose location string contains any of `remote/anywhere/work from home/wfh/distributed` OR matches `profile.search.location_accept`. Reject if matches `profile.search.location_reject_non_remote`. Unknown → keep (the scorer will decide).
6. Convert salary: `f"{currency}{min:,}-{currency}{max:,}/{interval}"`.
7. If JobSpy already returned a description ≥200 chars, set `full_description` and `detail_scraped_at` in the same INSERT (skip enrichment for this row).

### 8.2 Workday CXS API engine

Workday's `cxs` JSON endpoints. Ships the **48-employer registry** from §21 at `~/.nexscout/employers.yaml`.

Per employer × per query (filtered to tier ≤ `profile.search.workday_max_tier` default 2):

1. **Search:**
   ```
   POST {base_url}/wday/cxs/{tenant}/{site_id}/jobs
   Content-Type: application/json
   {"appliedFacets":{}, "limit":20, "offset":<n>, "searchText":"<query>"}
   ```
   Paginate `offset += 20` up to `total`, max 25 pages (= 500 results).
2. Filter by location (same accept/reject rules).
3. **Detail (per job):**
   ```
   GET {base_url}/wday/cxs/{tenant}/{site_id}{externalPath}
   ```
   Extract `jobPostingInfo.jobDescription` (strip HTML to plain text), `externalUrl` (= `application_url`), `jobReqId`, `timeType`, `remoteType`.
4. Insert with `strategy="workday_api"`, `site=<employer.name>`.

**Proxy support.** If `profile.proxy` is set as `host:port[:user:pass]`, build a global `urllib` opener with a `ProxyHandler`. Pure HTTP — no browser.

### 8.3 SmartExtract engine (AI-driven scraping)

For arbitrary career pages from §22. Two phases:

**Phase 1 — Page intelligence.** Open the URL with `undetected_chromedriver` (headful retry if cleaned-HTML < 5000 chars and no CAPTCHA signals). Intercept network responses (capture JSON-bodied responses whose URL contains `/api/`, `algolia`, `graphql`, or whose content-type is `application/json`). Collect:

- All `<script type="application/ld+json">` blocks parsed as JSON.
- `<script id="__NEXT_DATA__">` if present.
- Up to 50 `[data-testid]` elements with tag + first-80-chars of inner text.
- DOM stats: total elements, links, headings, lists, tables, articles, `[data-id]` count.
- Repeating card candidates: for every element with ≥3 same-tag children, score by `with_links * 2 + with_text`, return top 3 with parent/child selectors and 3 example cleaned-HTML snippets ≤5000 chars each.
- Full page HTML.

**Phase 1.5 — Judge.** For each captured API response, ask the LLM (judge task):

```
You are filtering intercepted API responses from a job listings website.
Decide if this API response contains actual job listing data
(titles, companies, locations, etc).

API Response Summary:
  URL: {url}
  Status: {status}
  Size: {size} chars
  Type: {type}
  Keys/Fields: {fields}
  Sample: {sample}

Is this job listing data? Answer in under 10 words. Return ONLY valid JSON:
{"relevant": true, "reason": "job objects with title/company"}
or
{"relevant": false, "reason": "auth endpoint"}

No explanation, no markdown, no thinking.
```

Drop responses voted `false`.

**Phase 2 — Strategy selection prompt:**

```
You are analyzing a job listings page to pick the best extraction strategy.

Below is a lightweight intelligence briefing — JSON-LD data, intercepted API
responses, data-testid attributes, and DOM statistics. NO raw DOM HTML.

Pick the BEST strategy:

1. "json_ld" — ONLY if briefing shows JobPosting JSON-LD entries (it will say "usable!")
2. "api_response" — ONLY if an intercepted API response has job-like fields
   (name, title, salary, description, location, slug)
3. "css_selectors" — when neither JSON-LD nor API data has job data

HOW TO THINK:
- If the briefing says "JSON-LD: NO JobPosting entries", do NOT pick json_ld.
- For api_response: "url_pattern" must be a substring matching one of the
  INTERCEPTED API URLs listed above (not the page URL!). Copy a unique part.
- For api_response: "items_path" must point to the ARRAY of items.
  Use dot notation with [n] only for traversing into a specific index to reach
  an inner array. E.g. items_path "results[0].hits" when data is
  {"results":[{"hits":[…]}]}.
- For api_response: field paths (title, salary, etc.) are relative to each item.
  If items are like {"_source":{"Title":"…"}}, use "_source.Title".
- For css_selectors: just return
  {"strategy":"css_selectors","reasoning":"...","extraction":{}} —
  selectors will be generated separately.

Return ONLY valid JSON.

For json_ld:
{"strategy":"json_ld","reasoning":"...","extraction":{
  "title":"title","salary":"baseSalary_path_or_null",
  "description":"description","location":"jobLocation[0].address.addressCountry",
  "url":"url_field"}}

For api_response:
{"strategy":"api_response","reasoning":"...","extraction":{
  "url_pattern":"actual.url.substring","items_path":"path.to.array",
  "title":"...","salary":"...","description":"...","location":"...","url":"..."}}

For css_selectors:
{"strategy":"css_selectors","reasoning":"...","extraction":{}}

Keep reasoning under 20 words. No markdown, no code fences.

INTELLIGENCE BRIEFING:
{briefing}
```

**Phase 3 — Execute.**

- `json_ld`: iterate `JSON-LD` entries with `@type=="JobPosting"`, resolve each path via dot/bracket notation, coerce dicts/lists to display strings.
- `api_response`: find the stored response by `url_pattern in resp.url`; walk `items_path`; for each item resolve field paths; coerce.
- `css_selectors`: send the cleaned page HTML (≤150k chars; remove `script/style/svg/noscript/iframe/link/meta/head/footer/nav`; strip layout-utility classes via regex `^([a-z]{1,2}-\d+|col-\d+|d-\w+|…|css-[a-z0-9]+|sc-…)$`) to the LLM with this **selector prompt**:

```
You are a senior web scraping engineer. Below is the cleaned HTML of a job
listings page.

Your task:
1. Find the repeating HTML elements that represent individual job listings.
2. Generate CSS selectors to extract data from them.

Return JSON with:
- "job_card": CSS selector matching each job card (must match ALL cards)
- "title": selector RELATIVE to the card for the job title
- "salary": selector relative to card for salary, or null
- "description": selector relative to card for description snippet, or null
- "location": selector relative to card for location, or null
- "url": selector relative to card for the <a> tag

Selector rules:
- SIMPLEST wins. [data-testid="job-card"] > li > div > [data-testid="job-card"].
- For data-testid/data-id with DYNAMIC values (data-testid="card-123") use
  prefix: [data-testid^="card-"].
- For STATIC values use exact: [data-testid="job-card"].
- Prefer semantic HTML (article, section, h2/h3) over div.
- NEVER use hashed/generated classes: sc-*, css-*, random 5-8 char strings.
- Max 2 levels deep; one level is best.
- The "url" selector should target an <a>; we extract its href.
- If the page has NO job listings visible, return {"error":"no job listings found"}.

Return ONLY valid JSON, no explanation, no markdown.

PAGE HTML:
{page_html}
```

Then apply the selectors to the original full HTML with BeautifulSoup. Result fields: `title, salary, description, location, url`.

**JSON extraction helper.** All LLM-JSON responses pass through `extract_json(text)` which: strips `<think>…</think>`, strips ```` ```json ``` ```` fences, finds the outermost balanced `{…}`, retries by chopping trailing chars until parse succeeds.

### 8.4 WebSearch engine (new)

For jobs that don't live on a known board. Provider chain (fall through on rate-limit or empty):

1. **Tavily** — `POST https://api.tavily.com/search` with `{"api_key":…,"query":…,"max_results":20}`.
2. **Brave** — `GET https://api.search.brave.com/res/v1/web/search` with `X-Subscription-Token`.
3. **DuckDuckGo HTML** — `GET https://duckduckgo.com/html/?q=<q>` parse `<a class="result__a">`.
4. **SearXNG** — self-hosted, `GET <searxng_url>/search?q=<q>&format=json`.
5. **Google Custom Search** — if `GOOGLE_CSE_KEY` and `GOOGLE_CSE_CX` set.

Build queries from a cartesian product:

```python
for query in profile.search.queries:
    for loc in profile.search.locations:
        for site in ["greenhouse.io", "lever.co", "ashbyhq.com",
                     "jobs.workable.com", "boards.greenhouse.io"]:
            yield f"\"{query.q}\" {loc.q} site:{site} after:{N}days"
```

Each returned URL is dedup'd by URL hash, then handed off:

- If the URL matches a known ATS host (greenhouse/lever/ashby/workable), enqueue directly with `strategy="websearch"` and run enrichment on it.
- Otherwise treat as a board/listing URL and run smartextract on it.

Daily cap: `profile.search.boards.websearch.queries_per_day`.

---

## 9. Stage 2 — Enrichment

Per pending row (`detail_scraped_at IS NULL` and `site NOT IN skip_set` where `skip_set = {"glassdoor","google","Workopolis"}`), open with `undetected_chromedriver`, then run a **3-tier cascade** (cheapest first):

**Tier 1 — JSON-LD.** Parse all `<script type="application/ld+json">`, recurse through `@graph`, find `@type == "JobPosting"`. Use `description` (HTML-cleaned via BeautifulSoup, converting `<br>` to `\n`, `<li>` to `- `, paragraphs to blank lines, then `re.sub(r"\n{3,}", "\n\n")`). For apply URL: `posting.directApply ? posting.url : posting.applicationContact.url ?? posting.url`. If description ≥ 50 chars, accept.

**Tier 2 — Deterministic CSS.** Try, in order:

```
APPLY_SELECTORS = [
  'a[href*="apply"]', 'a[data-testid*="apply"]', 'a[class*="apply"]',
  'a[aria-label*="pply"]', 'button[data-testid*="apply"]',
  'a#apply_button', '.postings-btn-wrapper a',
  'a.ashby-job-posting-apply-button',
  '#grnhse_app a[href*="apply"]',
  'a[data-qa="btn-apply"]', 'a[class*="btn-apply"]',
  'a[class*="apply-btn"]', 'a[class*="apply-button"]',
]

DESCRIPTION_SELECTORS = [
  '#job-description', '#job_description', '#jobDescriptionText',
  '.job-description', '.job_description',
  '[class*="job-description"]', '[class*="jobDescription"]',
  '[data-testid*="description"]', '[data-testid="job-description"]',
  '.posting-page .posting-categories + div', '#content .posting-page',
  '#app_body .content', '#grnhse_app .content',
  '.ashby-job-posting-description', '[class*="posting-description"]',
  '[class*="job-detail"]', '[class*="jobDetail"]',
  '[class*="job-content"]', '[class*="job-body"]',
  '[role="main"] article', 'main article',
  'article[class*="job"]', '.job-posting-content',
]
```

If neither yields ≥100 chars, fall through.

**Tier 3 — LLM.** Extract main content (try `main`, `article`, `[role="main"]`, `#content`, `.content`; else clone body and strip `nav/header/footer/script/style/noscript/svg/iframe`). Truncate to ≤30k chars. Prompt:

```
You are extracting job details from a single job posting page.

PAGE URL: {url}
PAGE TITLE: {title}

Find TWO things in the HTML below:
1. The full job description text (responsibilities, requirements, etc.)
2. The URL of the "Apply" button/link

Rules:
- For description: extract the FULL text. Include all sections.
- For apply URL: find the href of the link/button that starts the application.
- If you cannot find one, set it to null.
- Also detect: "cover_required" — true ONLY if the page clearly asks for a
  cover letter (a dedicated field, an upload labelled "cover letter",
  or text demanding one).

Return ONLY valid JSON:
{"full_description":"…","application_url":"https://…" or null,
 "cover_required": true|false}

No explanation, no markdown. Keep reasoning under 20 words.

HTML:
{content}
```

Save: `full_description`, `application_url`, `cover_required`, `detail_scraped_at`. On error (timeout, 404/410/451 → permanent; 408/429/500/502/503/504 → transient retry), record `detail_error`.

**Per-site delay between pages** (politeness):

```
RemoteOK: 3.0s, WelcomeToTheJungle: 2.0s, Job Bank Canada: 1.5s,
CareerJet Canada: 3.0s, Hacker News Jobs: 1.0s, BuiltIn Remote: 2.0s,
default: 2.0s
```

**URL resolution.** Before enrichment, walk every row whose `url` is relative; resolve against the site's base URL from §22 base-URLs map.

---

## 10. Stage 3 — Scoring

For each `(full_description IS NOT NULL AND fit_score IS NULL)`:

System prompt:

```
You are a job fit evaluator. Given a candidate's resume and a job description,
score how well the candidate fits the role.

SCORING CRITERIA:
- 9-10: Perfect match. Direct experience in nearly all required skills.
- 7-8: Strong match. Most required skills, minor gaps easily bridged.
- 5-6: Moderate match. Some relevant skills but missing key requirements.
- 3-4: Weak match. Significant skill gaps, substantial ramp-up.
- 1-2: Poor match. Completely different field or experience level.

IMPORTANT FACTORS:
- Weight technical skills heavily (languages, frameworks, tools).
- Consider transferable experience (automation, scripting, API work).
- Factor in project experience.
- Be realistic about experience level vs. job requirements.

RESPOND IN EXACTLY THIS FORMAT (no other text):
SCORE: [1-10]
KEYWORDS: [comma-separated ATS keywords from the job description that match
           or could match the candidate]
REASONING: [2-3 sentences explaining the score]
```

User payload:

```
RESUME:
<profile.to_resume_text()>

---

JOB POSTING:
TITLE: {title}
COMPANY: {site}
LOCATION: {location}

DESCRIPTION:
{full_description[:6000]}
```

Parse `SCORE:` (clamp 1..10; 0 on parse error). Save `fit_score`, `score_reasoning` (`f"{keywords}\n{reasoning}"`), `scored_at`.

---

## 11. Stage 4 — Tailoring

For `(fit_score >= profile.search.min_score AND tailored_resume_path IS NULL AND tailor_attempts < 5)`:

The LLM returns a JSON document; code (never the LLM) injects the header from the profile. Each retry starts a **fresh conversation** (no apologetic spirals). Up to 3 retries; banned-word severity depends on `--validation` mode (`strict`/`normal`/`lenient`).

System prompt builder reads `profile.skills`, `profile.facts`, `profile.exp.edu`, and the validator's `BANNED_WORDS` (§14):

```
You are a senior technical recruiter rewriting a resume to get this person
an interview.

Take the base resume and job description. Return a tailored resume as a JSON
object.

## RECRUITER SCAN (6 seconds):
1. Title — matches what they're hiring?
2. Summary — 2 sentences proving you've done this work
3. First 3 bullets of most recent role — verbs and outcomes match?
4. Skills — must-haves visible immediately?

## SKILLS BOUNDARY (real skills only):
Languages: {profile.skills.lang | join}
Frameworks: {profile.skills.fw | join}
Infra: {profile.skills.infra | join}
Data: {profile.skills.data | join}
Tools: {profile.skills.tools | join}

You MAY add 2-3 closely related tools (Kubernetes if Docker, Terraform if AWS,
Redis if PostgreSQL). No unrelated languages/frameworks.

## TAILORING RULES:
TITLE: Match the target role. Keep seniority (Senior/Lead/Staff). Drop suffixes.
SUMMARY: Rewrite from scratch. Lead with the 1-2 skills that matter most.
SKILLS: Reorder each category so the job's must-haves appear first.
Reframe EVERY bullet. Same real work, different angle. Never copy verbatim.
PROJECTS: Reorder by relevance. Drop irrelevant projects.
BULLETS: Strong verb + what you built + quantified impact. Vary verbs
(Built, Designed, Implemented, Reduced, Automated, Deployed, Operated,
Optimized). Most relevant first. Max 4 per section.

## VOICE:
- Write like a real engineer. Short, direct.
- GOOD: "Automated financial reporting with Python + API integrations,
        cut processing time from 10 hours to 2"
- BAD:  "Leveraged cutting-edge AI to drive transformative efficiencies"
- BANNED WORDS (any of these = validation failure):
  {BANNED_WORDS | join}
- No em dashes. Use commas, periods, or hyphens.

## HARD RULES:
- Do NOT invent work, companies, degrees, certifications.
- Do NOT change real numbers ({profile.facts.metrics | join}).
- Preserved companies: {profile.facts.companies | join} — names stay as-is.
- Preserved school: {profile.facts.school}.
- Must fit 1 page.

## OUTPUT: Return ONLY valid JSON. No markdown fences. No commentary. No
"here is" preamble.

{"title":"Role Title",
 "summary":"2-3 tailored sentences.",
 "skills":{"Languages":"...","Frameworks":"...","Infra":"...",
           "Data":"...","Tools":"..."},
 "experience":[{"header":"Title at Company","subtitle":"Tech | Dates",
                "bullets":["b1","b2","b3","b4"]}],
 "projects":[{"header":"Project — Description","subtitle":"Tech | Dates",
              "bullets":["b1","b2"]}],
 "education":"{profile.facts.school} | {profile.exp.edu}"}
```

User payload:

```
ORIGINAL RESUME:
<profile.to_resume_text()>

---

TARGET JOB:
TITLE: {title}
COMPANY: {site}
LOCATION: {location}

DESCRIPTION:
{full_description[:6000]}

Return the JSON:
```

**Validation layer 1 — JSON field check** (`validate_json_fields(data, profile, mode)`):

- Required keys present and non-empty: `title, summary, skills, experience, projects, education`.
- Skills block contains no entry from `FABRICATION_WATCHLIST` (§14).
- Every `profile.facts.companies` name appears in some `experience.header`.
- `profile.facts.school` appears in `education`.
- No `LLM_LEAK_PHRASES` (§14) anywhere → always an error.
- `BANNED_WORDS`: error in `strict`, warning in `normal`, ignored in `lenient`.

**Code assembles plain-text resume** (`assemble_resume_text(data, profile)`):

```
{profile.me.legal}
{data.title}
{profile.me.email} | {profile.me.phone} | {github_url} | {linkedin_url}

SUMMARY
{data.summary}

TECHNICAL SKILLS
Languages: …
…

EXPERIENCE
{header}
{subtitle}
- bullet
…

PROJECTS
…

EDUCATION
{data.education}
```

Sanitiser auto-fixes em/en dashes and smart quotes (`— → , ` ; `– → -` ; `“” → "` ; `‘’ → '`).

**Validation layer 2 — LLM judge** (skipped in `lenient`). Independent provider (default `profile.llm.judge`):

```
You are a resume quality judge. A tailoring engine rewrote a resume to target
a specific job. Your job is to catch LIES, not style changes.

Answer EXACTLY:
VERDICT: PASS or FAIL
ISSUES: (list problems, or "none")

## CONTEXT — what the engine was instructed to do (ALLOWED):
- Change the title to match the target role
- Rewrite the summary from scratch
- Reorder bullets and projects
- Reframe bullets to use the job's language
- Drop low-relevance bullets
- Reorder skills
- Change tone and wording extensively

## WHAT IS FABRICATION (FAIL):
1. Adding tools/languages/frameworks to TECHNICAL SKILLS that aren't allowed.
   Allowed skills are ONLY: {all_allowed_skills | join}
2. Inventing NEW metrics. Real metrics: {profile.facts.metrics | join}
3. Inventing work with no basis in any original bullet.
4. Adding companies, roles, degrees that don't exist.
5. Changing real numbers (inflating 80% to 95%, 500 nodes to 1000 nodes).

## WHAT IS NOT FABRICATION (do NOT fail for these):
- Rewording, combining, or splitting bullets as long as the underlying work is real
- Describing the same work with different emphasis
- Dropping bullets
- Reordering anything
- Changing the title or summary completely

## TOLERANCE:
Allow up to 3 minor stretches (closely-related tool, slight metric rewording).
Only FAIL for MAJOR lies: invented projects, fake companies, fake degrees,
wildly inflated numbers, skills from a completely different domain.

Be strict about major lies. Lenient about minor stretches and learnable skills.
Do not fail for style/tone/restructuring.
```

User payload: `JOB TITLE`, `ORIGINAL RESUME`, `TAILORED RESUME`, `Judge this tailored resume:`. Parse `VERDICT:` and `ISSUES:`.

**Retry loop.** On hard validation errors append them to `avoid_notes` and retry (fresh conversation, appended note section: `## AVOID THESE ISSUES (from previous attempt):`). After exhausting retries: status `failed_validation` if validator failed, `approved_with_judge_warning` if validator passed but judge failed on the last try, `approved` if both passed.

**Persist.** Write `.txt`, `_JOB.txt` (job description for traceability), `_REPORT.json` to `~/.nexscout/applications/<job_id>/` (we already write into the per-application bundle). Update `jobs.tailored_resume_path`, `tailored_at`, `tailor_attempts++` on success; only `tailor_attempts++` on failure.

**Then render LaTeX.** See §12.4.

---

## 12. Stage 5 — Cover Letter & LaTeX Engine

### 12.1 When to generate

Generate **only if** `cover_required=1` (set during enrichment) or the user sets `apply.always_cover_letter: true` in profile. Otherwise skip — saves tokens and avoids letters that recruiters never read.

### 12.2 Prompt

```
Write a cover letter for {profile.me.pref}. The goal is to get an interview.

STRUCTURE: 3 short paragraphs. Under 250 words. Every sentence must earn its place.

P1 (2-3 sentences): Open with a specific thing YOU built that solves THEIR
problem. Not "I'm excited about this role." Start with the work.

P2 (3-4 sentences): Pick 2 achievements from the resume most relevant to THIS
job. Use numbers. Frame as solving their problem.
Known projects: {profile.facts.projects | join}
Real metrics: {profile.facts.metrics | join}

P3 (1-2 sentences): One specific thing about the company from the job
description (product, technical challenge, team structure). Then close.
"Happy to walk through any of this in more detail." or "Let's discuss."

BANNED WORDS (validator rejects ANY of these):
{BANNED_WORDS | join}

ALSO BANNED (meta-commentary):
{LLM_LEAK_PHRASES | join}

BANNED PUNCTUATION: No em dashes (—) or en dashes (–). Use commas or periods.

VOICE:
- Write like a real engineer emailing someone they respect.
- Never narrate or explain ("This demonstrates my commitment to X" → bad).
- Never hedge ("might address some of your challenges" → bad).
- Every sentence should contain a number, a tool name, or a specific outcome.

FABRICATION = INSTANT REJECTION:
Allowed tools are ONLY: {all_skills | join}
Do NOT mention ANY tool not in this list. If the job asks for tools not listed,
talk about the work you did, not the tools.

Sign off: just "{profile.me.pref}"

Output ONLY the letter text. No subject lines. No "Here is the letter:".
Start DIRECTLY with "Dear Hiring Manager," and end with the name.
```

Strip any preamble before the first `Dear`. Validate (`validate_cover_letter`): must start with `Dear`, no em/en dashes, banned-word severity depends on mode, word count ≤275 in normal / ≤250 in strict, no leak phrases. Up to 3 retries, fresh conversation each time.

### 12.3 Output

Write the plain-text letter to `~/.nexscout/applications/<job_id>/cover_letter.txt`. Then render LaTeX.

### 12.4 LaTeX engine

`scoring/render/engine.py` picks the first available:

1. **Tectonic.** `tectonic --keep-logs -o <dir> <file>.tex`. Preferred — self-contained, downloads packages lazily.
2. **`latexmk -pdf -interaction=nonstopmode -outdir=<dir> <file>.tex`**.
3. **`pdflatex -interaction=nonstopmode -output-directory=<dir> <file>.tex`** (twice for refs).

Jinja2 environment uses non-default delimiters to coexist with LaTeX `{}`:

```python
env = Environment(
    block_start_string="<%", block_end_string="%>",
    variable_start_string="<<", variable_end_string=">>",
    comment_start_string="<#", comment_end_string="#>",
    autoescape=False,
)
env.filters["tex"] = latex_escape          # escapes & % $ # _ { } ~ ^ \
env.filters["money"] = lambda n, c: f"{c}{n:,}"
```

Two starter templates:

- `resume_classic.tex.j2` — single-column, Latin Modern Roman, A4. Sections: SUMMARY, TECHNICAL SKILLS, EXPERIENCE, PROJECTS, EDUCATION. Uses `enumitem` for tight bullets; `hyperref` for clickable email/LinkedIn.
- `resume_modern.tex.j2` — two-column, TeX Gyre Heros. Left rail: contact + skills. Right column: summary, experience, projects, education.
- `cover_letter.tex.j2` — block form, name + contact header, salutation, 3 paragraphs, sign-off.

Both resume templates accept the same context shape:

```python
{
  "me": profile.me,
  "title": data.title,
  "summary": data.summary,
  "skills": data.skills,          # dict[category -> str]
  "experience": data.experience,  # list of dicts
  "projects": data.projects,
  "education": data.education,
  "today": date.today().isoformat(),
}
```

Rendering populates `~/.nexscout/applications/<job_id>/resume.pdf` (and `.tex`, `.log`). Same for `cover_letter.pdf`.

---

## 13. Stage 6 — Application (Native agent backend)

### 13.1 Browser pool

Per worker `w ∈ [0, profile.apply.workers)`:

- Profile dir: `~/.nexscout/chrome-workers/worker-<w>/`. On first run, clone from an existing worker (preferred — has session cookies) or from the OS Chrome profile (Windows: `%LOCALAPPDATA%\Google\Chrome\User Data`; macOS: `~/Library/Application Support/Google/Chrome`; Linux: `~/.config/google-chrome`). Skip caches and locks (`ShaderCache, GrShaderCache, Service Worker, Cache, Code Cache, GPUCache, CacheStorage, Crashpad, BrowserMetrics, SafeBrowsing, Crowd Deny, MEIPreload, SSLErrorAssistant, recovery, Temp, SingletonLock, SingletonSocket, SingletonCookie`).
- Patch `<profile>/Default/Preferences`: set `profile.exit_type="Normal"`, `session.restore_on_startup=4` (open blank), remove `session.startup_urls`, `credentials_enable_service=false`, `password_manager.saving_enabled=false`, `autofill.profile_enabled=false` — this suppresses the "Restore pages?" nag after a kill.
- CDP port: `9222 + worker_id`. Before launch, kill any zombie on that port (Windows: `netstat -ano | findstr LISTENING` then `taskkill /F /T /PID`; *nix: `lsof -ti:<port>` then `kill -9 -<pgid>`).
- Launch via `undetected_chromedriver` with options: `--remote-debugging-port=<port>`, `--user-data-dir=<profile>`, `--profile-directory=Default`, `--no-first-run`, `--no-default-browser-check`, `--window-size=1024,768`, `--disable-session-crashed-bubble`, `--disable-features=InfiniteSessionRestore,PasswordManagerOnboarding`, `--hide-crash-restore-bubble`, `--noerrdialogs`, `--password-store=basic`, `--disable-save-password-bubble`, `--disable-popup-blocking`, `--use-fake-device-for-media-stream`, `--use-fake-ui-for-media-stream`, `--deny-permission-prompts`, `--disable-notifications`. Add `--headless=new` if `profile.apply.headless`.
- On *nix, start in a new process group (`os.setsid`) so we can kill the whole tree.

Apply additional stealth patches:

```js
Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
// remove cdc_ keys from window
Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});
Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});
```

Per-job: wipe and recreate `~/.nexscout/apply-workers/worker-<w>/` (file conflicts between jobs).

### 13.2 The native ReAct agent

Tools exposed to the LLM (JSON function-calling — works across Gemini, OpenAI, Anthropic, Ollama function-tools):

| Tool | Signature | Behaviour |
|------|-----------|-----------|
| `navigate` | `(url: str)` | `driver.get(url)`. Then run CAPTCHA DETECT. |
| `read_page` | `()` | Returns a simplified DOM snapshot: clean HTML stripped of layout-utility classes and non-allow-listed attrs (allow `id, href, data-testid, data-id, data-type, data-slug, role, aria-*, data-*, type, name, for, class<=30chars`). |
| `screenshot` | `(name: str)` | Save to `bundle_dir/screenshots/<NNN>_<name>.png`. |
| `click` | `(ref: str)` | XPath or CSS or `[data-testid=…]`. |
| `fill_form` | `(fields: dict[ref,value])` | Batch-fill. |
| `select` | `(ref: str, value: str)` | Open select element, click the option whose text matches. |
| `upload` | `(ref: str, path: str)` | File chooser. |
| `tabs` | `(action: "list"|"select", idx: int=0)` | Switch tabs (SSO popups). |
| `solve_captcha` | `()` | Detect → solve → inject. Mandatory. |
| `send_email` | `(to,subject,body,attachments[])` | For email-only postings; via SMTP using profile credentials if configured. |
| `wait` | `(ms: int)` | Bounded sleep. |
| `done` | `(result: ResultCode, reason: str="")` | Terminate the loop. |

### 13.3 Result codes

```
RESULT:APPLIED        — submitted successfully
RESULT:EXPIRED        — job closed
RESULT:CAPTCHA        — unsolvable CAPTCHA (only after CapSolver returns errorId>0)
RESULT:LOGIN_ISSUE    — could not sign in or sign up
RESULT:FAILED:not_eligible_location
RESULT:FAILED:not_eligible_work_auth
RESULT:FAILED:not_eligible_salary
RESULT:FAILED:already_applied
RESULT:FAILED:account_required
RESULT:FAILED:not_a_job_application
RESULT:FAILED:unsafe_permissions
RESULT:FAILED:unsafe_verification
RESULT:FAILED:sso_required
RESULT:FAILED:site_blocked
RESULT:FAILED:cloudflare_blocked
RESULT:FAILED:stuck
RESULT:FAILED:page_error
RESULT:FAILED:timeout
RESULT:FAILED:no_result_line
RESULT:FAILED:<custom reason>
```

### 13.4 System prompt for the apply agent

Built by `apply/prompt.py::build_prompt(job, tailored_resume, cover_letter, dry_run, profile)`. Returned to the LLM as the system message of the agent loop. Verbatim template (with `{…}` substitutions):

```
You are an autonomous job application agent. Your ONE mission: get this
candidate an interview. You have all the information and tools. Think
strategically. Act decisively. Submit the application.

== JOB ==
URL: {application_url or url}
Title: {title}
Company: {site}
Fit Score: {fit_score}/10

== FILES ==
Resume PDF (upload this): {bundle_dir}/resume.pdf
Cover Letter PDF (upload if asked): {bundle_dir}/cover_letter.pdf or N/A

== RESUME TEXT (use when filling text fields) ==
{tailored_resume_text}

== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==
{cover_letter_text or "None available. Skip if optional. If required,
write 2 factual sentences: (1) relevant experience from resume matching
this role, (2) available immediately and based in {city}."}

== APPLICANT PROFILE ==
Name: {me.legal}
Email: {me.email}
Phone: {me.phone}
Address: {address}, {city}, {region}, {country}, {postcode}
LinkedIn: {links.li}
GitHub: {links.gh}
Portfolio: {links.portfolio}
Website: {links.web}
Work Auth: {auth.authorized}
Sponsorship Needed: {auth.sponsor}
Work Permit: {auth.permit}
Salary Expectation: ${pay.expect} {pay.currency}
Years Experience: {exp.years}
Education: {exp.edu}
Available: {avail.start}
Age 18+: Yes
Background Check: Yes
Felony: No
Previously Worked Here: No
How Heard: Online Job Board
Gender: {eeo.gender}
Race: {eeo.race}
Veteran: {eeo.veteran}
Disability: {eeo.disability}

== YOUR MISSION ==
Submit a complete, accurate application. Use the profile and resume as
source data — adapt to fit each form's format.

If something unexpected happens and these instructions don't cover it,
figure it out yourself. You are autonomous. Navigate pages, read content,
try buttons, explore the site. The goal is always the same: submit the
application. Do whatever it takes to reach that goal.

== HARD RULES (never break these) ==
1. Never lie about citizenship, work authorization, criminal history,
   education, security clearance, licenses.
2. Work auth: {auth_rule}.
3. Name: Legal name = {me.legal}. Preferred = {me.pref}. Use "{me.pref} {last_name}"
   unless a field specifically says "legal name".

== NEVER DO THESE (immediate RESULT:FAILED) ==
- NEVER grant camera/mic/screen/location permissions →
  RESULT:FAILED:unsafe_permissions
- NEVER do video/audio/selfie/ID/biometric verification →
  RESULT:FAILED:unsafe_verification
- NEVER set up a freelancing profile (Mercor, Toptal, Upwork, Fiverr, Turing) →
  RESULT:FAILED:not_a_job_application
- NEVER agree to hourly/contract rates or "set your rate" flows.
- NEVER install browser extensions or download executables.
- NEVER enter payment info, bank details, SSN/SIN.
- NEVER click "Allow" on browser permission popups.
- If site is NOT a job application form (profile builder, skills marketplace,
  talent network, coding assessment) → RESULT:FAILED:not_a_job_application

== LOCATION CHECK (do this FIRST before any form) ==
Read the page. Determine work arrangement. Then:
- "Remote" / "work from anywhere" → ELIGIBLE. Apply.
- "Hybrid"/"onsite" in {accept_cities} → ELIGIBLE. Apply.
- "Hybrid"/"onsite" in another city but page says "remote OK" → ELIGIBLE.
- "Onsite only" in any city outside the list with NO remote option →
  RESULT:FAILED:not_eligible_location
- Overseas (India/Philippines/Europe) with no remote option →
  RESULT:FAILED:not_eligible_location
- Cannot determine → continue applying; if screening reveals onsite,
  answer honestly and let the system reject.

== SALARY (think, don't just copy) ==
${pay.expect} {pay.currency} is the FLOOR. Never go below it.
1. Posting shows a range (e.g. $120K-$160K) → answer the MIDPOINT ($140K).
2. Title says Senior/Staff/Lead/Principal/Architect/level II+ → minimum $110K
   {currency}. Use midpoint of posted range if higher.
3. Different currency? → target midpoint of their range. Convert if needed.
4. No salary info anywhere → use ${pay.expect} {pay.currency}.
5. Asked for a range → posted midpoint ±10%. No posted range →
   "${pay.range[0]}-${pay.range[1]} {currency}".
6. Hourly → divide your annual answer by 2080.

== SCREENING QUESTIONS (be strategic) ==
Hard facts → answer truthfully from profile (location, citizenship, clearance,
licenses, criminal/background).
Skills/tools → be confident. This candidate is a {target_title} with
{exp.years} years experience. "Do you have experience with [tool]?" in the same
domain (DevOps, backend, ML, cloud, automation) → YES. Engineers learn tools fast.
Open-ended ("Why do you want this role?", "Tell us about yourself") → 2-3
sentences. Specific to THIS job. Reference something from the job description.
No generic fluff. Sound like a real person.
EEO/demographics → "Decline to self-identify" or "Prefer not to say".

== STEP-BY-STEP ==
1. navigate(url). screenshot("landing"). solve_captcha() if detect returns one.
2. Read page. LOCATION CHECK. If ineligible, done(RESULT:FAILED:not_eligible_location).
3. Find Apply button. If "email resume to X":
     send_email(to=…, subject="Application for {title} — {display_name}",
                body=<2-3 sentence pitch + contact>, attachments=[resume_pdf])
     done(RESULT:APPLIED).
   After clicking Apply: snapshot. CAPTCHA DETECT — many sites trigger here.
4. Login wall?
   4a. URL is accounts.google.com / login.microsoftonline.com / okta.com /
       auth0.com / sso.cisco.com / any SSO → done(RESULT:FAILED:sso_required).
   4b. tabs("list") — new popup? Switch with tabs("select"). SSO there too?
       → sso_required.
   4c. Employer's own login form → sign in with {me.email} / {profile.password}.
   4d. After Login click → CAPTCHA DETECT (login pages often have invisible CAPTCHAs).
   4e. Sign in fails → try sign up with same email/password.
   4f. Need email verification → search_emails + read_email to fetch code.
   4g. tabs("list") again. Switch back to application tab.
   4h. All failed → done(RESULT:FAILED:login_issue). Do not loop.
5. Upload resume. ALWAYS upload fresh — delete existing first, then upload
   bundle/resume.pdf.
6. Upload cover letter if there's a field. Text field → paste; file → upload PDF.
7. Check ALL pre-filled fields. ATS parsers auto-fill — often WRONG.
   - "Current Job Title" → use the title from the TAILORED RESUME summary.
   - Compare every other field to the APPLICANT PROFILE. Fix mismatches.
   - Fill empty fields.
8. Answer screening questions per the rules above.
9. BEFORE clicking Submit/Apply, snapshot. Review EVERY field. Verify name,
   email, phone, location, work auth, resume uploaded, cover letter if applicable.
   Fix anything wrong. Only then click Submit.
   (Dry-run mode: review and done(RESULT:APPLIED, "dry run") WITHOUT clicking.)
10. After Submit: snapshot. CAPTCHA DETECT. tabs("list"). Look for thank-you /
    confirmation. done(RESULT:APPLIED).

== BROWSER EFFICIENCY ==
- snapshot ONCE per page. Then screenshot to verify (10× cheaper than re-snapshot).
- Re-snapshot only when you need element refs to click/fill.
- Multi-page forms (Workday, Taleo, iCIMS): snapshot each page, fill all,
  click Next, repeat.
- Fill ALL fields in ONE fill_form call.
- CAPTCHA AWARENESS: after navigate / Apply / Submit / Login / when stuck,
  run solve_captcha(). Invisible CAPTCHAs (Turnstile, reCAPTCHA v3) show no
  visual widget but block submissions silently.

== FORM TRICKS ==
- Popup/new tab → tabs("list") then tabs("select", idx).
- Upload-first pages (Workday/Lever/Ashby): click Select File, then upload,
  wait for parsing, then Next.
- Dropdown won't fill → click to open, click option.
- Checkbox won't check via fill → click it. Snapshot to verify.
- Phone with country prefix → type digits only: {digits_only(phone)}.
- Date → {today MM/DD/YYYY}.
- Honeypot (hidden, "leave blank") → skip.
- Format-sensitive → read the placeholder, match exactly.

== ASK USER ONLY IF NECESSARY ==
If a form asks for something not in this prompt AND not in the profile
addendum, AND it's not a screening you can answer from profile facts:
  done(RESULT:FAILED:question_required, reason="<the question>")
NexScout's orchestrator will park the job, surface the question to the user
via OpenClaw, then retry on the next tick after the user answers. Don't make
something up.

== WHEN TO GIVE UP ==
- Same page 3 times no progress → done(RESULT:FAILED:stuck).
- "no longer accepting" / closed → done(RESULT:EXPIRED).
- 500 / blank → done(RESULT:FAILED:page_error).
Stop immediately. Output your RESULT. Do not loop.
```

`auth_rule` is `"USC. Sponsorship needed: No."` for US citizens etc. — built from `profile.auth`.

### 13.5 Manual-ATS skip list

When `application_url` matches an entry in `profile.captcha.manual_ats_domains` (default `["ibegin.tcsapps.com"]`), mark `apply_status='manual'` and do NOT attempt.

### 13.6 Live dashboard

`apply/dashboard.py`: Rich `Live` table refreshed at 2 Hz with columns:

```
W | Job (title @ company)              | Status   | Time | Acts | Last Action | OK | Fail | Cost
```

`Recent Events` panel below shows the last 8 timestamped events (`[hh:mm:ss] [Wn] Starting: …`). Per-worker `WorkerState` dataclass: `worker_id, status, job_title, company, score, start_time, actions, last_action, jobs_applied, jobs_failed, total_cost`. Status palette: `starting/idle dim; applying yellow; applied bold green; failed red; expired dim red; captcha magenta; done bold`.

---

## 14. Validator Constants

`scoring/validator.py` exports these module-level constants. They are referenced by both the tailor/cover-letter prompts (to instruct the LLM what is banned) and by `validate_*` functions (to actually reject).

```python
BANNED_WORDS = [
  # Filler verbs and adjectives
  "passionate", "dedicated", "committed to",
  "utilizing", "utilize", "harnessing",
  "spearheaded", "spearhead", "orchestrated", "championed", "pioneered",
  "robust", "scalable solutions", "cutting-edge", "state-of-the-art", "best-in-class",
  "proven track record", "track record of success", "demonstrated ability",
  "strong communicator", "team player", "fast learner", "self-starter", "go-getter",
  "synergy", "cross-functional collaboration", "holistic",
  "transformative", "innovative solutions", "paradigm", "ecosystem",
  "proactive", "detail-oriented", "highly motivated",
  "seamless", "full lifecycle",
  "deep understanding", "extensive experience", "comprehensive knowledge",
  "thrives in", "excels at", "adept at", "well-versed in",
  "i am confident", "i believe", "i am excited",
  "plays a critical role", "instrumental in", "integral part of",
  "strong track record", "eager to", "eager",
  # Cover-letter-specific
  "this demonstrates", "this reflects", "i have experience with",
  "furthermore", "additionally", "moreover",
]

LLM_LEAK_PHRASES = [
  "i am sorry", "i apologize", "i will try", "let me try",
  "i am at a loss", "i am truly sorry", "apologies for",
  "i keep fabricating", "i will have to admit", "one final attempt",
  "one last time", "if it fails again", "persistent errors",
  "i am having difficulty", "i made an error", "my mistake",
  "here is the corrected", "here is the revised", "here is the updated",
  "here is my", "below is the", "as requested",
  "note:", "disclaimer:", "important:",
  "i have rewritten", "i have removed", "i have fixed",
  "i have replaced", "i have updated", "i have corrected",
  "per your feedback", "based on your feedback", "as per the instructions",
  "the following resume", "the resume below",
  "the following cover letter", "the letter below",
]

FABRICATION_WATCHLIST = {
  # Languages outside a typical SWE candidate's stack
  "c#", "c++", "golang", "rust", "ruby",
  "kotlin", "swift", "scala", "matlab",
  # Frameworks for wrong languages
  "spring", "django", "rails", "angular", "vue", "svelte",
  # Hard lies — certifications can't be stretched
  "certif", "certified", "pmp", "scrum master", "aws certified",
}

REQUIRED_SECTIONS = {"SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"}
```

`sanitize_text(t)`:

```python
t = t.replace(" — ", ", ").replace("—", ", ")  # em dash
t = t.replace("–", "-")                              # en dash
t = t.replace("“", '"').replace("”", '"')       # smart double quotes
t = t.replace("‘", "'").replace("’", "'")       # smart single quotes
return t.strip()
```

Match BANNED_WORDS with `\b` word boundaries (`re.search(r"\b" + re.escape(w) + r"\b", text.lower())`). LLM_LEAK_PHRASES match as substrings.

---

## 15. CAPTCHA — Mandatory

NexScout refuses to start `run` or `apply` if `profile.captcha.api_key` is unset.

### 15.1 Detection (JS run via `driver.execute_script`)

```javascript
(() => {
  const r = {}; const url = window.location.href;
  // 1. hCaptcha FIRST (hCaptcha uses data-sitekey too)
  const hc = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
  if (hc) { r.type = 'hcaptcha'; r.sitekey = hc.dataset.sitekey || hc.dataset.hcaptchaSitekey; }
  if (!r.type && document.querySelector('script[src*="hcaptcha.com"], iframe[src*="hcaptcha.com"]')) {
    const el = document.querySelector('[data-sitekey]');
    if (el) { r.type = 'hcaptcha'; r.sitekey = el.dataset.sitekey; }
  }
  // 2. Cloudflare Turnstile
  if (!r.type) {
    const cf = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
    if (cf) {
      r.type = 'turnstile'; r.sitekey = cf.dataset.sitekey || cf.dataset.turnstileSitekey;
      if (cf.dataset.action) r.action = cf.dataset.action;
      if (cf.dataset.cdata) r.cdata = cf.dataset.cdata;
    }
  }
  if (!r.type && document.querySelector('script[src*="challenges.cloudflare.com"]')) {
    r.type = 'turnstile_script_only'; r.note = 'Wait 3s and re-detect.';
  }
  // 3. reCAPTCHA v3
  if (!r.type) {
    const s = document.querySelector('script[src*="recaptcha"][src*="render="]');
    if (s) { const m = s.src.match(/render=([^&]+)/); if (m && m[1] !== 'explicit') { r.type = 'recaptchav3'; r.sitekey = m[1]; } }
  }
  // 4. reCAPTCHA v2
  if (!r.type) {
    const rc = document.querySelector('.g-recaptcha');
    if (rc) { r.type = 'recaptchav2'; r.sitekey = rc.dataset.sitekey; }
  }
  if (!r.type && document.querySelector('script[src*="recaptcha"]')) {
    const el = document.querySelector('[data-sitekey]'); if (el) { r.type = 'recaptchav2'; r.sitekey = el.dataset.sitekey; }
  }
  // 5. FunCaptcha (Arkose)
  if (!r.type) {
    const fc = document.querySelector('#FunCaptcha, [data-pkey], .funcaptcha');
    if (fc) { r.type = 'funcaptcha'; r.sitekey = fc.dataset.pkey; }
  }
  if (!r.type && document.querySelector('script[src*="arkoselabs"], script[src*="funcaptcha"]')) {
    const el = document.querySelector('[data-pkey]'); if (el) { r.type = 'funcaptcha'; r.sitekey = el.dataset.pkey; }
  }
  if (r.type) { r.url = url; return r; }
  return null;
})();
```

If result is `turnstile_script_only`, sleep 3s and re-run.

### 15.2 Solver protocol

```python
class CaptchaSolver(Protocol):
    def solve(self, kind: Literal["hcaptcha","recaptchav2","recaptchav3","turnstile","funcaptcha"],
              sitekey: str, url: str, **extras) -> str: ...
```

### 15.3 CapSolver implementation

Three steps:

1. `POST https://api.capsolver.com/createTask`:
   ```json
   {"clientKey":"<api_key>",
    "task":{"type":"<TASK_TYPE>","websiteURL":"<url>","websiteKey":"<sitekey>"}}
   ```
   TASK_TYPE map: `hcaptcha→HCaptchaTaskProxyLess`, `recaptchav2→ReCaptchaV2TaskProxyLess`, `recaptchav3→ReCaptchaV3TaskProxyLess`, `turnstile→AntiTurnstileTaskProxyLess`, `funcaptcha→FunCaptchaTaskProxyLess`. For `recaptchav3` add `"pageAction":"submit"` (or the actual action). For `turnstile` add `"metadata":{"action":"…","cdata":"…"}` if found.
2. Poll `POST https://api.capsolver.com/getTaskResult` with `{"clientKey":…,"taskId":…}`. Wait 3s between polls; max 10 polls (30s). Token field:
   - reCAPTCHA + hCaptcha → `solution.gRecaptchaResponse`
   - Turnstile → `solution.token`
   - FunCaptcha → `solution.token`
3. On `errorId > 0` or timeout → raise `CaptchaUnsolvable`. The agent emits `RESULT:CAPTCHA`. (CapSolver works server-side — visual challenges do not require us to interact with images; even "drag the pipe" hCaptchas solve via API token. Do not fall through visually.)

### 15.4 Injection (run via `execute_script`)

- **reCAPTCHA v2/v3:**
  ```js
  (token => {
    document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => { el.value = token; el.style.display = 'block'; });
    if (window.___grecaptcha_cfg) {
      const clients = window.___grecaptcha_cfg.clients;
      for (const k in clients) {
        const walk = (o,d)=>{ if (d>4||!o) return; for (const k in o) {
          if (typeof o[k] === 'function' && k.length < 3) try { o[k](token); } catch(e){}
          else if (typeof o[k] === 'object') walk(o[k], d+1);
        }}; walk(clients[k], 0);
      }
    }
  })('THE_TOKEN');
  ```
- **hCaptcha:**
  ```js
  (token => {
    const ta = document.querySelector('[name="h-captcha-response"], textarea[name*="hcaptcha"]');
    if (ta) ta.value = token;
    document.querySelectorAll('iframe[data-hcaptcha-response]').forEach(f => f.setAttribute('data-hcaptcha-response', token));
  })('THE_TOKEN');
  ```
- **Turnstile:**
  ```js
  (token => {
    const inp = document.querySelector('[name="cf-turnstile-response"], input[name*="turnstile"]');
    if (inp) inp.value = token;
  })('THE_TOKEN');
  ```
- **FunCaptcha:**
  ```js
  (token => {
    const inp = document.querySelector('#FunCaptcha-Token, input[name="fc-token"]');
    if (inp) inp.value = token;
    if (window.ArkoseEnforcement) try { window.ArkoseEnforcement.setConfig({data:{blob:token}}); } catch(e){}
  })('THE_TOKEN');
  ```

After injection: wait 2s, snapshot, verify (widget gone / green check). If not, click Submit. If still stuck after 2 retries: tokens have ~2 minute lifetime — fail with `RESULT:CAPTCHA`.

### 15.5 Other providers

`twocaptcha.py`: `POST https://2captcha.com/in.php` (form-encoded) → returns request id → `GET https://2captcha.com/res.php?key=…&action=get&id=…` until `OK|<token>`.
`anticaptcha.py`: structurally identical to CapSolver (`api.anti-captcha.com`).

---

## 16. Per-application bundle

```
~/.nexscout/applications/<job_id>/
├── job.json              # snapshot of the DB row at apply-time
├── resume.tex
├── resume.pdf
├── resume.txt            # plain-text version for paste-into-text-field fields
├── cover_letter.tex      # only if generated
├── cover_letter.pdf
├── cover_letter.txt
├── transcript.jsonl      # one JSON line per agent step (tool, args, result, ts)
├── screenshots/
│   ├── 001_landing.png
│   ├── 002_form.png
│   └── …
├── _REPORT.json          # tailor validator/judge report
└── result.json           # final {status, attempts, duration_ms, cost_usd, tokens}
```

`<job_id>` is the SQLite `id` column, padded to 6 digits.

---

## 17. Web UI

FastAPI + Jinja2 + HTMX + Tailwind (compiled to a single CSS file shipped under `static/`). Default bind `127.0.0.1:8765`. Cookie-based auth (bcrypt password stored in `~/.nexscout/web.toml`; HMAC-signed session cookie with key in `~/.nexscout/secrets.toml`, 24h TTL). CSRF via double-submit cookie on POSTs.

### 17.1 Pages

| Route | Purpose |
|-------|---------|
| `GET /` | Counters (`total`, `scored`, `applied`, `cost_usd`), score-distribution chart, "Recent Events" list, OpenClaw status (heartbeat last-tick, channel name). |
| `GET /jobs` | Paginated, filterable list. Filters: score range, site, status (any / applied / failed / pending / paused). Sortable by score, discovered_at. Server-side rendered rows; HTMX swap on filter change. |
| `GET /jobs/<id>` | Detail: title, company, location, score + keywords + reasoning, the full description (collapsible), embedded resume PDF via `<iframe>`, embedded cover letter PDF, transcript (rendered from `transcript.jsonl`), screenshot gallery, "Re-apply" button. |
| `GET /applications` | Same as `/jobs` but filtered to `apply_status='applied'`. Download all-bundles ZIP. |
| `GET /profile` | Form-edited YAML profile. Validates on save (Pydantic). Highlights errors. Shows current `meta.v` and a "Migrate" button when out-of-date. |
| `GET /questions` | Outstanding clarifying questions. Submit answer → `POST /api/answer` (writes to `learned-answers.md`, sets `pending_questions.answered_at`, clears `paused_for_question`). |
| `POST /controls/pause` `/resume` `/tick` | Pause/resume the continuous loop; trigger a tick manually. |
| `GET /metrics` | Prometheus-format metrics: per-stage counters, queue depth, cost_usd, captcha_solved. |
| `GET /api/*` | JSON variants of the above for tooling. |

### 17.2 Static-HTML export

`nexscout dashboard --export <file.html>` produces a self-contained file with: header stats, score-distribution bar chart, by-source table, and all jobs at fit_score ≥5 as cards. Pure HTML + inline CSS + tiny vanilla JS for client-side search/filter. No external deps; safe to email or commit.

---

## 18. OpenClaw skill manifest

`src/nexscout/openclaw/manifest.toml`:

```toml
[skill]
name = "nexscout"
version = "0.1.0"
description = "Always-on autonomous job-application agent."
homepage = "https://github.com/<owner>/NexScout"

[heartbeat]
command = "nexscout tick"
interval_minutes = 30
working_dir = "{{HOME}}/.nexscout"

[memory]
namespace = "nexscout"
files = ["learned-answers.md", "learned-employers.md", "do-not-ask-again.md", "feedback.md"]

[[commands]]
name = "status"
description = "Pipeline stats and last 5 events."
run = "nexscout status --format=openclaw"

[[commands]]
name = "apply"
description = "One-shot apply to a job URL."
args = ["url"]
run = "nexscout apply --url {{url}} --workers 1"

[[commands]]
name = "pause"
run = "nexscout controls pause"

[[commands]]
name = "resume"
run = "nexscout controls resume"

[[commands]]
name = "question"
description = "List pending clarifying questions."
run = "nexscout question list --format=openclaw"

[[commands]]
name = "answer"
description = "Answer a pending question."
args = ["question", "reply"]
run = "nexscout question answer --question \"{{question}}\" --reply \"{{reply}}\""
```

`nexscout tick` does the smallest useful slice of work and returns within a soft 5-minute budget:

```
1. Pull <=10 new jobs from each discovery engine (rate-limited per profile).
2. Enrich up to 20 pending jobs.
3. Score up to 50 pending jobs.
4. Tailor up to 5 high-fit jobs (LLM cost heavy).
5. Render any missing PDFs.
6. Apply to up to 3 jobs (browser cost heavy).
7. Surface pending questions to OpenClaw channels.
8. Print a one-line summary to stdout for OpenClaw to log.
```

Limits are configurable per `profile.openclaw.tick_budget`.

---

## 19. CLI specification

Typer-based.

```
nexscout init                                  # interactive wizard → ~/.nexscout/profile.yaml
nexscout doctor                                # check Python, Chromium, LaTeX engine, LLM, CAPTCHA
nexscout run [stages…]                         # discover|enrich|score|tailor|cover|render|all
   --stream                                    # streaming pipeline
   --workers N                                 # for discovery/enrichment
   --validation strict|normal|lenient          # default normal
   --dry-run
   --min-score N
nexscout apply
   --workers N --headless --dry-run --continuous
   --url URL                                   # one-shot
   --backend native|claude_code|openai_assistant
   --limit N
nexscout web [--init-pw] [--host 127.0.0.1] [--port 8765]
nexscout status [--format text|json|openclaw]
nexscout dashboard --export FILE
nexscout tick                                  # OpenClaw heartbeat entry
nexscout question list|answer
nexscout profile validate|migrate
nexscout chrome reset --worker N
nexscout budget show|reset
nexscout --version
```

`doctor` exits non-zero (and prints what's missing) when any of: Python <3.11, Chromium not found, no LaTeX engine on PATH, no LLM provider configured, no CAPTCHA api_key, `profile.yaml` invalid, `~/.nexscout` not writable.

**Tier model.** `doctor` reports a "Tier":
- **T1 Discovery** — Python + Chromium.
- **T2 LLM** — T1 + at least one LLM provider key (or local endpoint).
- **T3 Apply** — T2 + LaTeX engine + CAPTCHA provider. (Note: render-LaTeX is a soft requirement of T2 since tailoring writes text; it becomes mandatory at T3 because apply needs PDFs.)

---

## 20. Docker / docker-compose

`Dockerfile`:

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    tectonic fontconfig fonts-liberation \
    curl xvfb procps lsof ca-certificates && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e . && \
    pip install --no-cache-dir --no-deps python-jobspy && \
    pip install --no-cache-dir pydantic tls-client requests markdownify regex
ENV CHROME_PATH=/usr/bin/chromium
VOLUME ["/sandbox/nexscout"]
ENV NEXSCOUT_DIR=/sandbox/nexscout
ENTRYPOINT ["nexscout"]
CMD ["doctor"]
```

`docker-compose.yml`:

```yaml
services:
  nexscout:
    build: .
    volumes:
      - "${HOME}/.nexscout:/sandbox/nexscout"
    environment:
      - CAPTCHA_API_KEY
      - GEMINI_API_KEY
      - OPENAI_API_KEY
      - ANTHROPIC_API_KEY
      - TAVILY_API_KEY
    depends_on: [ollama]
    command: ["run"]

  ollama:
    image: ollama/ollama
    volumes: [ollama:/root/.ollama]
    profiles: ["local-llm"]

  openclaw:
    image: openclaw/openclaw:latest
    volumes:
      - "${HOME}/.openclaw:/root/.openclaw"
      - "${HOME}/.nexscout:/sandbox/nexscout"
    profiles: ["openclaw"]

volumes:
  ollama:
```

Profiles let users opt in: `docker compose --profile local-llm --profile openclaw up`.

---

## 21. Workday employer registry (ship as default `employers.yaml`)

Each entry shape: `{name, tenant, site_id, base_url}`. URL format: `<base_url>/wday/cxs/<tenant>/<site_id>/jobs`.

```yaml
employers:
  td:              {name: "TD Bank",            tenant: td,                site_id: TD_Bank_Careers,                 base_url: "https://td.wd3.myworkdayjobs.com"}
  cibc:            {name: "CIBC",               tenant: cibc,              site_id: search,                          base_url: "https://cibc.wd3.myworkdayjobs.com"}
  rbc:             {name: "RBC",                tenant: rbc,               site_id: RBCGLOBAL1,                      base_url: "https://rbc.wd3.myworkdayjobs.com"}
  bmo:             {name: "BMO",                tenant: bmo,               site_id: External,                        base_url: "https://bmo.wd3.myworkdayjobs.com"}
  manulife:        {name: "Manulife",           tenant: manulife,          site_id: MFCJH_Jobs,                      base_url: "https://manulife.wd3.myworkdayjobs.com"}
  sunlife:         {name: "Sun Life",           tenant: sunlife,           site_id: Experienced-Jobs,                base_url: "https://sunlife.wd3.myworkdayjobs.com"}
  desjardins:      {name: "Desjardins",         tenant: desjardins,        site_id: Desjardins,                      base_url: "https://desjardins.wd10.myworkdayjobs.com"}
  intact:          {name: "Intact Financial",   tenant: intactfc,          site_id: intactfc,                        base_url: "https://intactfc.wd3.myworkdayjobs.com"}
  aviva:           {name: "Aviva Canada",       tenant: aviva,             site_id: External,                        base_url: "https://aviva.wd1.myworkdayjobs.com"}
  tmx:             {name: "TMX Group",          tenant: tmx,               site_id: TMX_Careers,                     base_url: "https://tmx.wd3.myworkdayjobs.com"}
  brookfield:      {name: "Brookfield",         tenant: brookfield,        site_id: brookfield,                      base_url: "https://brookfield.wd5.myworkdayjobs.com"}
  fis:             {name: "FIS Global",         tenant: fis,               site_id: SearchJobs,                      base_url: "https://fis.wd5.myworkdayjobs.com"}
  mastercard:      {name: "Mastercard",         tenant: mastercard,        site_id: CorporateCareers,                base_url: "https://mastercard.wd1.myworkdayjobs.com"}
  paypal:          {name: "PayPal",             tenant: paypal,            site_id: jobs,                            base_url: "https://paypal.wd1.myworkdayjobs.com"}
  cppib:           {name: "CPP Investments",    tenant: cppib,             site_id: cppinvestments,                  base_url: "https://cppib.wd10.myworkdayjobs.com"}
  omers:           {name: "OMERS",              tenant: omers,             site_id: OMERS_External,                  base_url: "https://omers.wd3.myworkdayjobs.com"}
  otpp:            {name: "Ontario Teachers",   tenant: otppb,             site_id: OntarioTeachers_Careers,         base_url: "https://otppb.wd3.myworkdayjobs.com"}
  psp:             {name: "PSP Investments",    tenant: investpsp,         site_id: psp_careers,                     base_url: "https://investpsp.wd3.myworkdayjobs.com"}
  cdpq:            {name: "CDPQ",               tenant: cdpq,              site_id: CDPQ,                            base_url: "https://cdpq.wd10.myworkdayjobs.com"}
  hoopp:           {name: "HOOPP",              tenant: hoopp,             site_id: HOOPP,                           base_url: "https://hoopp.wd10.myworkdayjobs.com"}
  aimco:           {name: "AIMCo",              tenant: aimco,             site_id: AIMCoCareers,                    base_url: "https://aimco.wd10.myworkdayjobs.com"}
  blackberry:      {name: "BlackBerry",         tenant: bb,                site_id: BlackBerry,                      base_url: "https://bb.wd3.myworkdayjobs.com"}
  ciena:           {name: "Ciena",              tenant: ciena,             site_id: Careers,                         base_url: "https://ciena.wd5.myworkdayjobs.com"}
  workday:         {name: "Workday",            tenant: workday,           site_id: Workday,                         base_url: "https://workday.wd5.myworkdayjobs.com"}
  salesforce:      {name: "Salesforce",         tenant: salesforce,        site_id: External_Career_Site,            base_url: "https://salesforce.wd12.myworkdayjobs.com"}
  nvidia:          {name: "NVIDIA",             tenant: nvidia,            site_id: NVIDIAExternalCareerSite,        base_url: "https://nvidia.wd5.myworkdayjobs.com"}
  netflix:         {name: "Netflix",            tenant: netflix,           site_id: Netflix,                         base_url: "https://netflix.wd1.myworkdayjobs.com"}
  cisco:           {name: "Cisco",              tenant: cisco,             site_id: Cisco_Careers,                   base_url: "https://cisco.wd5.myworkdayjobs.com"}
  intel:           {name: "Intel",              tenant: intel,             site_id: External,                        base_url: "https://intel.wd1.myworkdayjobs.com"}
  adobe:           {name: "Adobe",              tenant: adobe,             site_id: external_experienced,            base_url: "https://adobe.wd5.myworkdayjobs.com"}
  motorola:        {name: "Motorola Solutions", tenant: motorolasolutions, site_id: Careers,                         base_url: "https://motorolasolutions.wd5.myworkdayjobs.com"}
  thomson_reuters: {name: "Thomson Reuters",    tenant: thomsonreuters,    site_id: External_Career_Site,            base_url: "https://thomsonreuters.wd5.myworkdayjobs.com"}
  moderna:         {name: "Moderna",            tenant: modernatx,         site_id: M_tx,                            base_url: "https://modernatx.wd1.myworkdayjobs.com"}
  servicenow:      {name: "ServiceNow",         tenant: servicenow,        site_id: ServiceNowCareers,               base_url: "https://servicenow.wd1.myworkdayjobs.com"}
  docusign:        {name: "DocuSign",           tenant: docusign,          site_id: External,                        base_url: "https://docusign.wd5.myworkdayjobs.com"}
  uber:            {name: "Uber",               tenant: uber,              site_id: uberCareers,                     base_url: "https://uber.wd5.myworkdayjobs.com"}
  pwc:             {name: "PwC",                tenant: pwc,               site_id: Global_Experienced_Careers,      base_url: "https://pwc.wd3.myworkdayjobs.com"}
  bdo:             {name: "BDO",                tenant: bdo,               site_id: BDO,                             base_url: "https://bdo.wd3.myworkdayjobs.com"}
  telus:           {name: "TELUS International",tenant: telusinternational,site_id: External,                        base_url: "https://telusinternational.wd3.myworkdayjobs.com"}
  telus_health:    {name: "TELUS Health",       tenant: lifeworks,         site_id: External,                        base_url: "https://lifeworks.wd3.myworkdayjobs.com"}
  canadian_tire:   {name: "Canadian Tire",      tenant: canadiantirecorporation, site_id: Enterprise_External_Careers_Site, base_url: "https://canadiantirecorporation.wd3.myworkdayjobs.com"}
  pc_financial:    {name: "PC Financial",       tenant: myview,            site_id: pc_financial,                    base_url: "https://myview.wd3.myworkdayjobs.com"}
  cae:             {name: "CAE",                tenant: cae,               site_id: career,                          base_url: "https://cae.wd3.myworkdayjobs.com"}
  magna:           {name: "Magna International",tenant: magna,             site_id: Magna,                           base_url: "https://magna.wd3.myworkdayjobs.com"}
  mlse:            {name: "MLSE",               tenant: mlse,              site_id: MLSE,                            base_url: "https://mlse.wd3.myworkdayjobs.com"}
  olg:             {name: "OLG",                tenant: olg,               site_id: Careers,                         base_url: "https://olg.wd3.myworkdayjobs.com"}
  enbridge:        {name: "Enbridge",           tenant: enbridge,          site_id: enbridge_careers,                base_url: "https://enbridge.wd3.myworkdayjobs.com"}
  canadian_solar:  {name: "Canadian Solar",     tenant: canadiansolar,     site_id: CanadianSolar,                   base_url: "https://canadiansolar.wd5.myworkdayjobs.com"}
```

---

## 22. Direct career-site registry (ship as default `sites.yaml`)

```yaml
# Skip these ATS hosts during apply — unsolvable CAPTCHAs.
manual_ats:
  - "ibegin.tcsapps.com"

blocked:
  sites: [glassdoor, google, accenture, AccentureCareers, Workopolis]
  url_patterns:
    - "%glassdoor%"
    - "%google.com/about/careers%"
    - "%google.jobs%"
    - "%accenture%"
    - "%workopolis.com/out%"

blocked_sso:
  - accounts.google.com
  - login.microsoftonline.com
  - okta.com
  - auth0.com
  - sso.cisco.com

# Used by enrichment to resolve relative URLs.
base_urls:
  "Job Bank Canada":   "https://www.jobbank.gc.ca"
  "CareerJet Canada":  "https://www.careerjet.ca"
  "BuiltIn Remote":    "https://builtin.com"
  "Hacker News Jobs":  "https://news.ycombinator.com/"
  "Workopolis":        "https://www.workopolis.com"
  "WeWorkRemotely":    "https://weworkremotely.com"
  "Startup.jobs":      "https://startup.jobs"
  "Nodesk":            "https://nodesk.co"
  "Talent.com":        "https://www.talent.com"
  "JustRemote":        "https://justremote.co"
  "Arc.dev":           "https://arc.dev"
  "Himalayas":         "https://himalayas.app"
  "Techstars Jobs":    "https://www.techstars.com"
  "Randstad Canada":   "https://www.randstad.ca/jobs/search/"

# Scrape targets. {query_encoded} / {location_encoded} are URL-encoded.
sites:
  # ── Searchable (URL takes search params) ──
  - {name: "Eluta",              type: search, url: "https://www.eluta.ca/search?q={query_encoded}&l={location_encoded}"}
  - {name: "Talent.com",         type: search, url: "https://www.talent.com/jobs?k={query_encoded}&l={location_encoded}"}
  - {name: "Randstad Canada",    type: search, url: "https://www.randstad.ca/jobs/?keywords={query_encoded}&location={location_encoded}"}
  - {name: "CareerJet Canada",   type: search, url: "https://www.careerjet.ca/search/jobs?s={query_encoded}&l={location_encoded}"}
  - {name: "Job Bank Canada",    type: search, url: "https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring={query_encoded}&locationstring={location_encoded}&fage=2&sort=D"}
  - {name: "Dice",               type: search, url: "https://www.dice.com/jobs?q={query_encoded}&location=Remote&pageSize=100"}
  - {name: "SimplyHired",        type: search, url: "https://www.simplyhired.com/search?q={query_encoded}&l={location_encoded}"}
  - {name: "PowerToFly",         type: search, url: "https://powertofly.com/jobs/?keywords={query_encoded}&remote=true"}
  - {name: "Techstars Jobs",     type: search, url: "https://jobs.techstars.com/jobs?keywords={query_encoded}"}
  - {name: "Startup.jobs",       type: search, url: "https://startup.jobs/?q={query_encoded}&remote=true"}
  - {name: "WelcomeToTheJungle", type: search, url: "https://www.welcometothejungle.com/en/jobs?query={query_encoded}&refinementList%5Bremote%5D%5B%5D=fulltime"}
  - {name: "Otta",               type: search, url: "https://otta.com/jobs/all?title=software+engineer&remote=true"}

  # ── Static (one URL, scraped wholesale) ──
  - {name: "RemoteOK",       type: static, url: "https://remoteok.com/remote-dev-jobs"}
  - {name: "WeWorkRemotely", type: static, url: "https://weworkremotely.com/categories/remote-programming-jobs"}
  - {name: "Remotive",       type: static, url: "https://remotive.com/remote-jobs/software-dev"}
  - {name: "JustRemote",     type: static, url: "https://justremote.co/remote-developer-jobs"}
  - {name: "Himalayas",      type: static, url: "https://himalayas.app/jobs/developer"}
  - {name: "Working Nomads", type: static, url: "https://www.workingnomads.com/jobs?category=development"}
  - {name: "Remote.co",      type: static, url: "https://remote.co/remote-jobs/developer/"}
  - {name: "Nodesk",         type: static, url: "https://nodesk.co/remote-jobs/"}
  - {name: "DynamiteJobs",   type: static, url: "https://dynamitejobs.com/category/remote-development-jobs"}
  - {name: "4DayWeek",       type: static, url: "https://4dayweek.io/remote-jobs/software-engineer"}
  - {name: "Hacker News Jobs", type: static, url: "https://news.ycombinator.com/jobs"}
  - {name: "BuiltIn Remote",   type: static, url: "https://builtin.com/jobs/remote/dev-engineering"}
  - {name: "Wellfound",        type: static, url: "https://wellfound.com/role/l/software-engineer/canada"}
  - {name: "Arc.dev",          type: static, url: "https://arc.dev/remote-jobs/developer"}
  - {name: "Jobgether",        type: static, url: "https://jobgether.com/remote-jobs/software-engineer"}
  - {name: "TopStartups",      type: static, url: "https://topstartups.io/jobs/?job_location=Remote"}
  - {name: "Jobspresso",       type: static, url: "https://jobspresso.co/remote-work/remote-software-development/"}
  - {name: "FlexJobs",         type: static, url: "https://www.flexjobs.com/remote-jobs/computer-it"}
```

`type: search` URLs are expanded with each query/location pair before crawling. `type: static` URLs are crawled once per tick.

---

## 23. Code quality requirements

- **Ruff** (`ruff check` and `ruff format`) enforced in CI and pre-commit. Line length 120. Target `py311`. Rule set: `E,F,W,I,UP,B,SIM,RET,PL,RUF`. Zero errors after every commit.
- **Mypy** `--strict` on `core/`, `llm/`, `scoring/`, `captcha/`, `apply/orchestrator.py`, `apply/agent.py`. Other modules `--strict` once they stabilise.
- **Pytest** with `pytest-cov`. Required coverage: `core/ ≥ 90%`, `llm/ ≥ 80%`, `scoring/ ≥ 80%`, `captcha/ ≥ 70%`, `apply/orchestrator.py ≥ 80%`.
- **Pre-commit hooks**: `ruff`, `ruff-format`, `mypy`, `end-of-file-fixer`, `trailing-whitespace`, `check-merge-conflict`, `check-yaml`, `check-toml`.
- **CI** (GitHub Actions matrix): Python 3.11/3.12/3.13 × Ubuntu/Windows/macOS. Steps: install, ruff, mypy, pytest. A nightly job builds the Docker image and runs `docker run --rm nexscout doctor` to verify Chromium + Tectonic install.

---

## 24. Dependencies

`pyproject.toml`:

```toml
[project]
name = "nexscout"
version = "0.1.0"
description = "Always-on, autonomous job-application agent."
readme = "README.md"
license = "AGPL-3.0-only"
requires-python = ">=3.11"
authors = [{name = "NexScout Authors"}]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Environment :: Console",
  "License :: OSI Approved :: GNU Affero General Public License v3",
  "Programming Language :: Python :: 3.11",
]
dependencies = [
  "typer>=0.9",
  "rich>=13",
  "pydantic>=2.5",
  "pydantic-settings>=2.0",
  "pyyaml>=6.0",
  "httpx>=0.27",
  "beautifulsoup4>=4.12",
  "lxml>=5.0",
  "undetected-chromedriver>=3.5",
  "selenium>=4.21",
  "jinja2>=3.1",
  "fastapi>=0.110",
  "uvicorn>=0.27",
  "python-multipart>=0.0.9",
  "passlib[bcrypt]>=1.7",
  "itsdangerous>=2.2",
  "anthropic>=0.34",
  "openai>=1.30",
  "google-generativeai>=0.7",
  "ollama>=0.3",
  "pandas>=2.0",
  "playwright>=1.40",   # only for headless fallback when undetected-chromedriver can't reach
]

[project.optional-dependencies]
dev = ["pytest>=7", "pytest-cov>=4", "ruff>=0.5", "mypy>=1.10", "pre-commit>=3", "types-PyYAML"]
web = []   # listed for clarity; deps already in main set
openclaw = []

[project.scripts]
nexscout = "nexscout.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/nexscout"]

[tool.hatch.build]
artifacts = ["src/nexscout/scoring/render/templates/*.j2",
             "src/nexscout/openclaw/manifest.toml"]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E","F","W","I","UP","B","SIM","RET","PL","RUF"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_ignores = true
```

`python-jobspy` is installed by users via the two-step incantation (it pins an exact numpy version in metadata that conflicts with pip's resolver but works at runtime):

```
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
```

---

## 25. Roadmap (Milestones)

Each milestone is independently demonstrable. The agent picks up at the lowest-numbered incomplete milestone.

### M1 — Foundation (Day 1–2)
- [ ] Repo scaffolding, `pyproject.toml`, `.ruff.toml`, AGPL `LICENSE`.
- [ ] `core/config.py`, `core/database.py`, `core/profile.py` (load+validate YAML, `to_resume_text()`).
- [ ] `cli.py` skeleton: `init`, `doctor`, `--version`.
- [ ] CI green on an empty test suite.

### M2 — LLM router & scoring (Day 3–4)
- [ ] `llm/router.py` with Gemini, OpenAI, Anthropic, Ollama, LM Studio.
- [ ] `llm/budget.py` ledger.
- [ ] `scoring/scorer.py` end-to-end on a fake job dict; returns 1..10.

### M3 — Discovery (Day 5–8)
- [ ] `discovery/jobspy.py`.
- [ ] `discovery/workday.py` + ships `employers.yaml` (§21).
- [ ] `discovery/smartextract.py` (intelligence collector + 3 strategies).
- [ ] `discovery/websearch.py` (Tavily + DDG to start).
- [ ] Smoke: 200+ jobs in DB.

### M4 — Enrichment (Day 9–10)
- [ ] `enrichment/detail.py` with the 3-tier cascade and `undetected_chromedriver`.
- [ ] Stealth patches, retry/backoff, timeout handling.

### M5 — Tailor → LaTeX → PDF (Day 11–13)
- [ ] `scoring/tailor.py`, `scoring/validator.py`, `scoring/cover_letter.py`.
- [ ] `scoring/render/engine.py` + two templates.
- [ ] First end-to-end resume PDF rendered for a real job.

### M6 — CAPTCHA (Day 14)
- [ ] `captcha/detect.py` + `captcha/capsolver.py` + tests on known sitekeys.
- [ ] `doctor` blocks runs without provider; `run`/`apply` refuse without one.

### M7 — Native apply backend (Day 15–19)
- [ ] `browser/pool.py`, `browser/driver.py`, `browser/stealth.py`.
- [ ] `apply/orchestrator.py` (atomic acquire, worker_loop, mark_result, release_lock).
- [ ] `apply/agent.py` ReAct loop + tools.
- [ ] `apply/prompt.py` builder.
- [ ] Successful submission against Greenhouse + Lever test postings.
- [ ] `apply/dashboard.py` live Rich dashboard.

### M8 — Web UI (Day 20–22)
- [ ] FastAPI + auth + session.
- [ ] Pages: dashboard, jobs list, job detail (inline PDF), applications, profile, questions, controls, metrics.

### M9 — OpenClaw integration (Day 23–25)
- [ ] `openclaw/manifest.toml`, `openclaw/skill.py`, `openclaw/memory.py`, `openclaw/tick.py`.
- [ ] `nexscout tick` performs a bounded unit of work within ~5 min.
- [ ] End-to-end question/answer loop via OpenClaw channel.

### M10 — Docker (Day 26)
- [ ] Dockerfile builds; `docker compose up` runs the full stack.
- [ ] Profiles: `local-llm`, `openclaw`.

### M11 — Hardening (Day 27–28)
- [ ] Ruff/mypy clean; pytest coverage targets met.
- [ ] CHANGELOG, README, `examples/split/*.yaml`.
- [ ] Tag `v0.1.0`.

---

## 26. Reference prompt (for a fresh session)

Paste this prompt into a fresh chat. It is fully self-contained — the agent needs only `plan.md` and write access to the working directory; it does not need any other project to reference.
