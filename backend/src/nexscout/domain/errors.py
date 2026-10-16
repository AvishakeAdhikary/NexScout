"""Typed domain errors, mapped to HTTP problem responses in the API layer."""

from __future__ import annotations


class DomainError(Exception):
    """Base class. `code` is a stable machine-readable identifier."""

    code = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(DomainError):
    """Resource missing *or not owned by the actor*. Never reveals which."""

    code = "not_found"


class Conflict(DomainError):
    code = "conflict"


class ValidationFailed(DomainError):
    code = "validation_failed"


class AuthenticationFailed(DomainError):
    code = "authentication_failed"


class PermissionDenied(DomainError):
    code = "permission_denied"


class RateLimited(DomainError):
    code = "rate_limited"


class InvalidTransition(DomainError):
    code = "invalid_transition"


class ConcurrencyConflict(Conflict):
    """Optimistic-locking version mismatch."""

    code = "concurrency_conflict"
