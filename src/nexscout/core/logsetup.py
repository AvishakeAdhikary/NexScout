"""Shared file logging so the dashboard's Logs tab can show backend activity.

The autopilot, web, and MCP run as separate processes. Each calls
:func:`setup_file_logging` with its role, which attaches a rotating file handler
writing to ``~/.nexscout/logs/nexscout-<role>.log`` (one writer per file, so
rotation never races). Console logging is left as-is. :func:`tail` reads the
last N lines of a role's log for the Logs viewer.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import nexscout_dir

#: Roles that write their own log file (the Logs tab can show each).
ROLES: tuple[str, ...] = ("autopilot", "web", "mcp")

_CONFIGURED: set[str] = set()


def _logs_dir() -> Path:
    return nexscout_dir() / "logs"


def log_file_path(role: str) -> Path:
    return _logs_dir() / f"nexscout-{role}.log"


def setup_file_logging(role: str, *, level: int = logging.INFO) -> Path:
    """Attach a rotating file handler for ``role`` to the root logger (idempotent)."""
    path = log_file_path(role)
    path.parent.mkdir(parents=True, exist_ok=True)
    if role in _CONFIGURED:
        return path
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    _CONFIGURED.add(role)
    return path


def tail(role: str = "autopilot", lines: int = 300) -> list[str]:
    """Return the last ``lines`` log lines for ``role`` (newest last)."""
    if role not in ROLES:
        role = "autopilot"
    try:
        text = log_file_path(role).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


__all__ = ["ROLES", "log_file_path", "setup_file_logging", "tail"]
