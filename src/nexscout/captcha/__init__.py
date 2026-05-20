"""CAPTCHA detect → solve → inject (§15 of plan.md).

The provider implementations expose a common :class:`CaptchaSolver` protocol.
Detection is a verbatim JS snippet evaluated in the page (:mod:`.detect`).
"""

from __future__ import annotations

from .anticaptcha import AntiCaptchaSolver
from .base import CAPTCHA_KINDS, CaptchaKind, CaptchaSolver
from .capsolver import TASK_TYPE, CapSolverSolver
from .detect import DETECT_JS, detect_in_driver
from .inject import INJECT_JS, inject
from .twocaptcha import TwoCaptchaSolver

__all__ = [
    "CAPTCHA_KINDS",
    "DETECT_JS",
    "INJECT_JS",
    "TASK_TYPE",
    "AntiCaptchaSolver",
    "CapSolverSolver",
    "CaptchaKind",
    "CaptchaSolver",
    "TwoCaptchaSolver",
    "detect_in_driver",
    "inject",
]
