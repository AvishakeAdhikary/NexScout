# ADR-0011: Read-only MCP server with personal access tokens; Electron desktop shell

- **Status:** Accepted
- **Date:** 2026-10-17
- **Relates to:** ADR-0007 (MCP and A2A), ADR-0003 (tenant isolation)

## Context
Users want local AI assistants to use their NexScout data, and a desktop app. Both must keep
the guarantees: tenant isolation, no consequential action without approval in NexScout's own
UI, private entries never shared, and secrets protected.

## Decision

### MCP server
- `nexscout mcp` runs a stdio MCP server built with the official Python SDK (`mcp` 2.x,
  `MCPServer`).
- It authenticates once at start-up with a **personal access token** from
  `NEXSCOUT_MCP_TOKEN`. The token never goes on the command line, where other local users could
  read it from the process list.
- **Tokens:** `nxs_` plus 256 random bits. Only the SHA-256 digest is stored, the token is shown
  once, it expires (7 to 365 days), it is revocable, and creation and revocation are audited.
  Tokens can't log in to the web app.
- **Tools:** list cases, confirmed profile (non-private only), explained matches, applications,
  application timeline, documents, document Markdown.
  - All tools are read-only (`readOnlyHint`).
  - They call the same use cases as the API, inside a tenant transaction (owner filters plus RLS).
  - Results say that external text is untrusted data.
- There are no write tools. Submitting, sending and approving stay in NexScout's UI.

### MCP client and A2A
- An MCP client for external servers stays deferred: nothing is configured to verify it against,
  and each server would need an allowlist and approval design.
- A2A stays deferred (ADR-0007): there is still no remote agent that would consume it.

### Desktop shell (`apps/desktop`, Electron 44)
- **Windows:** contextIsolation, sandbox, no nodeIntegration, no `<webview>`.
- **Navigation:** allowed only within the app origin. Other links open in the system browser
  (http, https and mailto only). Pop-ups are denied and all device permissions refused.
- **Preloads:** the app window gets a two-field preload; the setup window gets exactly two
  IPC calls, both validated again in the main process.
- **Modes:**
  - *remote*: https, or http only to loopback.
  - *local*: starts `nexscout serve`, `nexscout worker` and `next start` from a checkout, waits
    until the API is ready, the worker is running and the web server responds, and writes logs
    to `userData/logs`.
- **Master key:** local mode generates the key once and keeps it encrypted with Electron
  `safeStorage` (the OS keychain). It reaches the backend through the environment only.
- Packaged with electron-builder: NSIS on Windows, DMG on macOS, AppImage on Linux.

## Consequences
- The desktop app is a shell, not a self-contained bundle. Local mode needs a NexScout checkout,
  Postgres, uv and Node. A single-file installer that bundles Python, Node and Postgres isn't
  provided (see KNOWN_LIMITATIONS).
- Quitting stops the local servers forcibly (on Windows, `taskkill /T /F`). In-flight background
  steps are recovered by lease expiry, which matches the at-least-once design (ADR-0008).
- Installers are unsigned until a code-signing certificate is configured.
