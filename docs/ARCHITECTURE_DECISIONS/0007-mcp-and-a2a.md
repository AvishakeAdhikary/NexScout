# ADR-0007: MCP and A2A adoption boundaries

- **Status:** Proposed. Finalized in M9 after verifying SDK APIs.
- **Date:** 2026-10-16

## Context
§9.3 requires genuine MCP and A2A implementations where useful, but forbids forcing internal calls
through network protocols. Internal orchestration is LangGraph inside one worker process.

## Decision (initial)
- **MCP server (NexScout → external clients):** expose read-only resources and tools (list cases,
  accepted profile facts, opportunities, application status) through the official `mcp` SDK (2.x),
  authenticated with a per-user personal access token and scoped to that user. No write tools at first.
- **MCP client (external tool servers → NexScout agents):** only servers on an allowlist in
  `provider_configs`. Their outputs are treated as untrusted data and never as instructions. Each tool
  gets an explicit permission scope and timeout.
- **A2A:** not adopted for internal agents. All logical agents run in-process as LangGraph nodes.
  We will consider an A2A *server* exposing the Research capability once there is a real
  remote-agent consumer, using the official `a2a-sdk` (1.x) with auth, task lifecycle and
  correlation IDs.

## Consequences
No fake "MCP" naming of internal function calls. KNOWN_LIMITATIONS lists A2A as not implemented
until a justified consumer exists.
