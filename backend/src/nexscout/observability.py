"""Structured logging with mandatory secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|cookie|session|csrf|credential|"
    r"master[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_KEY_LIKE = re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}\b")
REDACTED = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _BEARER.sub(r"\1 " + REDACTED, value)
        return _KEY_LIKE.sub(REDACTED, value)
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if _SENSITIVE_KEY.search(str(k)) else _redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove secrets from every log record. Keys are matched by name and values by pattern."""
    for key in list(event_dict.keys()):
        if key == "event":
            event_dict[key] = _redact_value(event_dict[key])
        elif _SENSITIVE_KEY.search(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_processor,
    ]
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=level.upper(), stream=sys.stdout, format="%(message)s")


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
