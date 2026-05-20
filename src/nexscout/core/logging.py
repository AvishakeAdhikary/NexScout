"""Logging: rich console + JSON structured records."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from rich.console import Console
from rich.logging import RichHandler

_console: Console | None = None


def console() -> Console:
    """Return a process-wide rich Console (stderr-bound to keep stdout clean)."""
    global _console
    if _console is None:
        _console = Console(stderr=True)
    return _console


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "taskName",
            }:
                continue
            payload[k] = v
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", json_mode: bool = False) -> None:
    """Configure root logger. Either rich console or JSON to stdout."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    if json_mode:
        h: logging.Handler = logging.StreamHandler(stream=sys.stdout)
        h.setFormatter(JsonFormatter())
    else:
        h = RichHandler(console=console(), rich_tracebacks=True, show_path=False)

    root.addHandler(h)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
