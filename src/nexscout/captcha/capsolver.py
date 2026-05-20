"""CapSolver implementation per §15.3 — verbatim 3-step flow.

1. ``POST https://api.capsolver.com/createTask`` with the per-kind task type.
2. Poll ``POST https://api.capsolver.com/getTaskResult`` every 3s up to 10
   times (30s budget).
3. On ``errorId > 0`` or timeout, raise :class:`CaptchaUnsolvable`.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ..core.errors import CaptchaUnsolvable
from .base import CaptchaKind

log = logging.getLogger(__name__)

API_BASE = "https://api.capsolver.com"
POLL_INTERVAL = 3.0
MAX_POLLS = 10  # 30 second budget per §15.3

# Verbatim §15.3 task-type map.
TASK_TYPE: dict[str, str] = {
    "hcaptcha": "HCaptchaTaskProxyLess",
    "recaptchav2": "ReCaptchaV2TaskProxyLess",
    "recaptchav3": "ReCaptchaV3TaskProxyLess",
    "turnstile": "AntiTurnstileTaskProxyLess",
    "funcaptcha": "FunCaptchaTaskProxyLess",
}


def _extract_token(kind: CaptchaKind, solution: dict[str, Any]) -> str:
    """Per §15.3, token field varies by kind."""
    if kind in ("recaptchav2", "recaptchav3", "hcaptcha"):
        token = solution.get("gRecaptchaResponse")
    elif kind in ("turnstile", "funcaptcha"):
        token = solution.get("token")
    else:
        token = solution.get("token") or solution.get("gRecaptchaResponse")
    if not isinstance(token, str) or not token:
        raise CaptchaUnsolvable(f"CapSolver returned no token for {kind!r}")
    return token


class CapSolverSolver:
    """CapSolver-backed :class:`~.base.CaptchaSolver`."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        api_base: str = API_BASE,
        poll_interval: float = POLL_INTERVAL,
        max_polls: int = MAX_POLLS,
    ) -> None:
        if not api_key:
            raise CaptchaUnsolvable("CapSolver requires an api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(
        self,
        kind: CaptchaKind,
        sitekey: str,
        url: str,
        **extras: object,
    ) -> str:
        """Run the verbatim 3-step flow. Returns the token."""
        if kind not in TASK_TYPE:
            raise CaptchaUnsolvable(f"unsupported CAPTCHA kind: {kind!r}")
        task_id = self._create_task(kind, sitekey=sitekey, url=url, **extras)
        solution = self._poll_task(task_id)
        return _extract_token(kind, solution)

    def close(self) -> None:
        if self._owned_client:
            self._client.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_task(self, kind: CaptchaKind, *, sitekey: str, url: str, **extras: object) -> dict[str, Any]:
        task: dict[str, Any] = {
            "type": TASK_TYPE[kind],
            "websiteURL": url,
            "websiteKey": sitekey,
        }
        if kind == "recaptchav3":
            action = extras.get("action", "submit")
            task["pageAction"] = action
        if kind == "turnstile":
            metadata: dict[str, Any] = {}
            action = extras.get("action")
            cdata = extras.get("cdata")
            if action:
                metadata["action"] = action
            if cdata:
                metadata["cdata"] = cdata
            if metadata:
                task["metadata"] = metadata
        return task

    def _create_task(self, kind: CaptchaKind, *, sitekey: str, url: str, **extras: object) -> str:
        payload = {
            "clientKey": self.api_key,
            "task": self._build_task(kind, sitekey=sitekey, url=url, **extras),
        }
        resp = self._client.post(f"{self.api_base}/createTask", json=payload)
        resp.raise_for_status()
        data = resp.json() or {}
        if int(data.get("errorId", 0)) > 0:
            raise CaptchaUnsolvable(f"createTask failed: {data.get('errorDescription') or data}")
        task_id = data.get("taskId")
        if not task_id:
            raise CaptchaUnsolvable(f"createTask returned no taskId: {data}")
        return str(task_id)

    def _poll_task(self, task_id: str) -> dict[str, Any]:
        for _ in range(self.max_polls):
            resp = self._client.post(
                f"{self.api_base}/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
            )
            resp.raise_for_status()
            data = resp.json() or {}
            if int(data.get("errorId", 0)) > 0:
                raise CaptchaUnsolvable(f"getTaskResult error: {data.get('errorDescription') or data}")
            status = data.get("status")
            if status == "ready":
                solution = data.get("solution") or {}
                if not isinstance(solution, dict):
                    raise CaptchaUnsolvable(f"unexpected solution shape: {solution!r}")
                return solution
            time.sleep(self.poll_interval)
        raise CaptchaUnsolvable(f"CapSolver timeout after {self.max_polls * self.poll_interval:.0f}s")
