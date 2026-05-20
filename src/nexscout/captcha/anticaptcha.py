"""anti-captcha.com implementation per §15.5.

Structurally identical to CapSolver (3-step createTask / getTaskResult flow)
but hits ``api.anti-captcha.com`` and uses ``...TaskProxyless`` (lowercase
'less') task-type names.
"""

from __future__ import annotations

from typing import Any

from .base import CaptchaKind
from .capsolver import CapSolverSolver

API_BASE = "https://api.anti-captcha.com"

# anti-captcha uses lowercase "less" in task type names.
TASK_TYPE: dict[str, str] = {
    "hcaptcha": "HCaptchaTaskProxyless",
    "recaptchav2": "RecaptchaV2TaskProxyless",
    "recaptchav3": "RecaptchaV3TaskProxyless",
    "turnstile": "TurnstileTaskProxyless",
    "funcaptcha": "FunCaptchaTaskProxyless",
}


class AntiCaptchaSolver(CapSolverSolver):
    """anti-captcha-backed :class:`~.base.CaptchaSolver`.

    Shares the CapSolver poll/extract flow; overrides only the API base URL
    and task-type map.
    """

    def __init__(self, api_key: str, **kwargs: Any) -> None:
        kwargs.setdefault("api_base", API_BASE)
        super().__init__(api_key, **kwargs)

    def _build_task(
        self,
        kind: CaptchaKind,
        *,
        sitekey: str,
        url: str,
        **extras: object,
    ) -> dict[str, Any]:
        task: dict[str, Any] = {
            "type": TASK_TYPE[kind],
            "websiteURL": url,
            "websiteKey": sitekey,
        }
        if kind == "recaptchav3":
            task["pageAction"] = extras.get("action", "submit")
            task["minScore"] = extras.get("min_score", 0.3)
        if kind == "turnstile":
            action = extras.get("action")
            cdata = extras.get("cdata")
            if action:
                task["action"] = action
            if cdata:
                task["cdata"] = cdata
        return task
