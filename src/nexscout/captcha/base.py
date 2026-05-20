"""CaptchaSolver protocol shared by every provider implementation (§15.2)."""

from __future__ import annotations

from typing import Literal, Protocol

CaptchaKind = Literal["hcaptcha", "recaptchav2", "recaptchav3", "turnstile", "funcaptcha"]

CAPTCHA_KINDS: tuple[str, ...] = (
    "hcaptcha",
    "recaptchav2",
    "recaptchav3",
    "turnstile",
    "funcaptcha",
)


class CaptchaSolver(Protocol):
    """Provider contract: every backend exposes a single :meth:`solve` call."""

    def solve(
        self,
        kind: CaptchaKind,
        sitekey: str,
        url: str,
        **extras: object,
    ) -> str:
        """Solve the given CAPTCHA and return the token (caller injects it)."""
        ...
