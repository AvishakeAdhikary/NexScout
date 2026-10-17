# Changelog

Releases are created automatically from `main` after CI passes (`.github/workflows/release.yml`).
Each one bumps the **minor** version and lists its commits in the GitHub release notes. This
file summarizes the larger milestones.

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
