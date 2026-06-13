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


#: Severity order used by the level filter (a chosen level shows itself + worse).
LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _level_ok(line: str, min_level: str | None) -> bool:
    """True if ``line`` is at/above ``min_level``. Continuation lines (e.g. a
    traceback body, which has no level token) are always kept so multi-line
    records stay intact."""
    if not min_level or min_level == "ALL":
        return True
    parts = line.split(None, 2)
    if len(parts) < 2:
        return True
    try:
        return LEVELS.index(parts[1]) >= LEVELS.index(min_level)
    except ValueError:
        return True


def file_size(role: str) -> int:
    """Current byte size of a role's log file (0 if absent)."""
    try:
        return log_file_path(role).stat().st_size
    except OSError:
        return 0


def tail(role: str = "autopilot", lines: int = 300, level: str | None = None) -> list[str]:
    """Return the last ``lines`` log lines for ``role`` (newest last), filtered by level."""
    if role not in ROLES:
        role = "autopilot"
    try:
        text = log_file_path(role).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = [ln for ln in text.splitlines() if _level_ok(ln, level)]
    return out[-lines:]


def read_since(role: str, offset: int, level: str | None = None) -> tuple[list[str], int]:
    """Read only the bytes appended since ``offset`` (the incremental tail).

    Returns ``(new_lines, new_offset)``. If the file shrank (rotated/cleared)
    or ``offset`` is out of range, it resumes at the current end without
    dumping the whole file, so the viewer only ever streams *new* content.
    """
    if role not in ROLES:
        role = "autopilot"
    path = log_file_path(role)
    try:
        size = path.stat().st_size
    except OSError:
        return [], 0
    if offset < 0 or offset > size:
        return [], size
    if offset == size:
        return [], size
    try:
        with path.open("rb") as f:
            f.seek(offset)
            data = f.read()
            new_offset = f.tell()
    except OSError:
        return [], offset
    chunk = data.decode("utf-8", "replace")
    lines = [ln for ln in chunk.splitlines() if _level_ok(ln, level)]
    return lines, new_offset


__all__ = ["LEVELS", "ROLES", "file_size", "log_file_path", "read_since", "setup_file_logging", "tail"]
