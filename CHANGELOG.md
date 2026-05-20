# Changelog

All notable changes to NexScout will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-21

First public release. NexScout is feature-complete against the specification
in `plan.md` — every milestone M1-M11 has shipped.

### Added

- **M1 — Foundation.** Repository scaffolding, `pyproject.toml`, AGPL-3.0
  licence, `.ruff.toml`, pre-commit hooks, CI workflow. `core/config.py`,
  `core/database.py` (single column registry per §5, idempotent
  `init_db`, forward-only `ensure_columns`), `core/profile.py` (Pydantic
  Profile model with `to_resume_text()` and `${env:NAME}` substitution).
  Typer CLI skeleton: `init`, `doctor`, `--version`.
- **M2 — LLM router & scoring.** `llm/router.py` with Gemini, OpenAI,
  Anthropic, Ollama, LM Studio, vLLM, llama.cpp providers. `llm/budget.py`
  SQLite-backed ledger. Retry policy with exponential backoff and qwen
  "/no_think" optimisation. `scoring/scorer.py` end-to-end with verbatim
  §10 prompt.
- **M3 — Discovery.** Four engines: `discovery/jobspy.py`,
  `discovery/workday.py` with the 48-employer registry (§21),
  `discovery/smartextract.py` (intelligence collector + judge + strategy +
  selector LLM prompts, §8.3 verbatim), `discovery/websearch.py` (Tavily +
  Brave + DuckDuckGo + SearXNG fall-through). `extract_json` LLM-JSON
  helper. `sites.yaml` registry (§22) with `manual_ats`, `blocked`,
  `blocked_sso`, `base_urls`, and 30 search/static sources.
- **M4 — Enrichment.** `enrichment/detail.py` with the 3-tier cascade
  (JSON-LD -> deterministic CSS -> verbatim §9 LLM prompt). Per-site
  politeness delays, URL resolution, transient/permanent error handling.
- **M5 — Tailor, cover letter, LaTeX.** `scoring/tailor.py` (verbatim §11
  prompt, JSON output, retries on fresh conversations, judge), `scoring/
  cover_letter.py` (verbatim §12.2 prompt, validator, retries), `scoring/
  validator.py` (verbatim §14 BANNED_WORDS, LLM_LEAK_PHRASES,
  FABRICATION_WATCHLIST, REQUIRED_SECTIONS, `sanitize_text`), `scoring/
  judge.py` independent LLM verdict, `scoring/render/engine.py`
  (tectonic/latexmk/pdflatex), three Jinja2 LaTeX templates with the
  custom `<%`/`%>`/`<<`/`>>` delimiters (§12.4).
- **M6 — Mandatory CAPTCHA.** `captcha/detect.py` (verbatim §15.1 detection
  JS), `captcha/capsolver.py`, `captcha/twocaptcha.py`,
  `captcha/anticaptcha.py`, `captcha/inject.py` (verbatim §15.4 injection
  snippets for reCAPTCHA v2/v3, hCaptcha, Turnstile, FunCaptcha). `doctor`
  refuses to start `run`/`apply` without a provider.
- **M7 — Native apply backend.** `browser/pool.py` per-worker Chrome
  profile clone, zombie killer, restore-page suppression. `browser/
  stealth.py` cdc / webdriver / plugins patches. `apply/orchestrator.py`
  atomic acquire (§5 SQL), worker loop, mark-result with permanent-failure
  classification. `apply/agent.py` ReAct loop, `apply/tools.py` (`navigate`,
  `read_page`, `click`, `fill_form`, `upload`, `tabs`, `solve_captcha`,
  `send_email`, `wait`, `done`), `apply/prompt.py` builder (verbatim §13.4
  template), `apply/dashboard.py` Rich `Live` per-worker table.
- **M8 — Web UI.** FastAPI app, bcrypt + HMAC-signed cookie sessions,
  CSRF double-submit. Pages: dashboard, jobs list, job detail (inline
  PDFs + screenshot gallery + transcript), applications, profile editor,
  questions, controls, Prometheus metrics. HTMX server-side rendering;
  pure-CSS Tailwind output bundled under `static/`.
- **M9 — OpenClaw integration.** `openclaw/manifest.toml` (§18 verbatim),
  `openclaw/skill.py` slash-command handlers, `openclaw/memory.py`
  Markdown reader/writer, `openclaw/tick.py` bounded-unit-of-work entry
  with per-stage budgets from `profile.openclaw.tick_budget`.
- **M10 — Docker.** `Dockerfile` (python:3.11-slim + chromium +
  chromium-driver + tectonic + fontconfig + fonts-liberation + xvfb +
  procps + lsof), `docker-compose.yml` with `local-llm` and `openclaw`
  profiles, `.dockerignore`. Docs: `docs/openclaw.md`,
  `docs/architecture.md` (Mermaid pipeline), `docs/latex-templates.md`,
  `docs/developer-guide.md`.
- **M11 — Hardening.** Ruff clean, mypy strict on §23-listed modules,
  coverage targets met (`core/ ≥ 90%`, `llm/ ≥ 80%`, `scoring/ ≥ 80%`,
  `captcha/ ≥ 70%`, `apply/orchestrator.py ≥ 80%`). Verbatim audit tests
  (`tests/unit/test_prompts_verbatim.py`) compare the in-code constants
  against `plan.md` modulo placeholder names; the §13.4 apply template
  was tightened to match plan.md byte-equally outside `{...}` placeholders.
  `CHANGELOG.md` and a full `README.md` with quickstart + run modes.

### Notes

- `python-jobspy` must still be installed via the two-step incantation
  (`pip install --no-deps python-jobspy` then `pip install pydantic
  tls-client requests markdownify regex`) because its pinned numpy
  version conflicts with pip's resolver but works at runtime.
- The Jinja2 environment for LaTeX templates uses non-default delimiters
  `<% %>` / `<< >>` / `<# #>` to coexist with LaTeX `{}`.
- All six §-pinned LLM prompts (§8.3 judge/strategy/selector, §9, §10,
  §11, §12.2, §13.4) are guarded by verbatim-equality tests against
  `plan.md`. Verbatim means verbatim.
