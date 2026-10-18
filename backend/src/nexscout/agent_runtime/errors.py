"""What a user sees when a step or run fails (AGENTS.md: user-visible errors only through here).

Errors we raise on purpose carry a message written for people (DomainError, "the document was
deleted", a site that couldn't be reached, a provider that refused). Anything else is a bug: the
user gets a plain sentence with a reference, and the exception with its traceback goes to the log
under that reference. Python class names and internals never reach the screen.
"""

from __future__ import annotations

import secrets

import structlog

from nexscout.agent_runtime.context import TokenBudgetExceeded, UncertainOutcome
from nexscout.domain.errors import DomainError
from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed
from nexscout.infrastructure.llm.base import ProviderError

log = structlog.get_logger()

# Exceptions whose message is written for the user.
USER_FACING: tuple[type[BaseException], ...] = (
    DomainError,
    LookupError,
    PermissionError,
    FetchBlocked,
    FetchFailed,
    ProviderError,
    TokenBudgetExceeded,
    UncertainOutcome,
)
GENERIC = (
    "Something went wrong in this step. It was logged with reference {ref}; "
    "try again or retry the step."
)


def user_message(exc: BaseException, *, where: str = "") -> str:
    """A safe, human message for `exc` (at most 500 characters)."""
    if isinstance(exc, USER_FACING) or getattr(exc, "user_facing", False):
        text = str(exc).strip()
        if text and not isinstance(exc, (KeyError, IndexError)):  # LookupError subclasses: bugs
            return text[:500]
    ref = secrets.token_hex(4)
    log.error("unexpected_error", ref=ref, where=where, error_type=type(exc).__name__, exc_info=exc)
    return GENERIC.format(ref=ref)
