"""NexScout Model Context Protocol (MCP) server package.

Exposes NexScout's autonomous job-application pipeline to MCP-aware agents
(notably the OpenClaw gateway) as a set of network-reachable tools. The
OpenClaw container (Node) cannot spawn the NexScout container (Python) as a
stdio child process, so the server is served over **Streamable HTTP** and
reached by URL on the shared ``nexscout-net`` Docker network.

See :mod:`nexscout.mcp.server` for the tool definitions and entry point.
"""

from __future__ import annotations

__all__ = ["server"]
