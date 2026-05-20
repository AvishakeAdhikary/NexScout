"""NexScout exception hierarchy."""

from __future__ import annotations


class NexScoutError(Exception):
    """Base class for all NexScout errors."""


class ConfigError(NexScoutError):
    """Raised when configuration is invalid or missing."""


class ProviderError(NexScoutError):
    """Raised when an LLM provider call fails."""


class ValidationError(NexScoutError):
    """Raised when tailor/cover-letter validation fails."""


class CaptchaUnsolvable(NexScoutError):
    """Raised when a CAPTCHA cannot be solved."""


class ApplyError(NexScoutError):
    """Raised by the apply orchestrator on terminal failure."""
