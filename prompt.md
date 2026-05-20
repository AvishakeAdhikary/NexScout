**NexScout — Build Task**

You are building **NexScout** from scratch in the current working directory. NexScout is an always-on, autonomous job-application agent: it discovers jobs across the web, scores them against a YAML user profile, tailors a LaTeX-rendered resume (and cover letter when required) per application, and submits the application via an undetected Chrome driver with mandatory CAPTCHA solving. It runs continuously inside an OpenClaw / NemoClaw heartbeat, exposes a FastAPI + HTMX web UI, and stores every application's full bundle on disk.

The **only** specification you need is `plan.md` in this directory. Read it in full before doing anything else. Every prompt, every constant, every schema, every default registry, every file path, every algorithm is inlined there. Do not invent details that contradict it. Do not consult external repositories.

Working rules:

1. License: AGPL-3.0-only. Language: Python 3.11+. Line length: 120. Ruff rule set: `E,F,W,I,UP,B,SIM,RET,PL,RUF`. After every commit, `ruff check src/` must return 0 errors.
2. The repository layout is in §4 of `plan.md` — follow it exactly. Create `src/nexscout/` as the package root.
3. The user profile is **always** the YAML schema in §3. Never reintroduce JSON profiles or hardcoded personal data; every personal value is read at runtime from `~/.nexscout/profile.yaml`.
4. SQLite schema is in §5 — use the "one column registry" pattern with idempotent `init_db()` and forward-only `ensure_columns()`. Thread-local connections, WAL on.
5. LLM access goes through `LLMRouter` (§6) only. Never call provider SDKs from anywhere else.
6. Undetected Chrome is the default browser; CAPTCHA solving is mandatory (`doctor` blocks runs without a provider).
7. Resumes and cover letters render via the LaTeX engine in §12.4 with Jinja2 `<<>>` delimiters; PDFs go into the per-application bundle directory (§16).
8. The agent's apply-stage system prompt is the verbatim template in §13.4 with placeholders filled from the profile and the job row.
9. Validator banned-word, leak-phrase, and fabrication-watchlist constants are in §14 — copy them verbatim into `scoring/validator.py`.
10. CAPTCHA detection JS and CapSolver flow are in §15 — copy verbatim.
11. Workday and direct-site registries ship as defaults from §21 and §22.
12. OpenClaw integration: manifest in §18, memory contract in §2, `nexscout tick` is the heartbeat entry. Pending clarifying questions live in the `pending_questions` table and are surfaced to OpenClaw channels by the tick.
13. Tests: write them as you go. The roadmap (§25) defines the milestone order — start at the lowest-numbered incomplete milestone.

First action: read `plan.md` in full, then propose the very next concrete change you will make (file name, brief content sketch) and wait for my approval before writing code. Do **not** scaffold the entire repo in one shot — go milestone by milestone, smallest-useful-slice each turn.
