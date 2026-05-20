"""2captcha.com implementation per §15.5.

``POST https://2captcha.com/in.php`` (form-encoded) returns a request id, then
``GET https://2captcha.com/res.php?key=…&action=get&id=…`` polls until
``OK|<token>``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from ..core.errors import CaptchaUnsolvable
from .base import CaptchaKind

log = logging.getLogger(__name__)

API_BASE = "https://2captcha.com"
POLL_INTERVAL = 5.0
MAX_POLLS = 24  # 2 minutes

# Per-kind "method" parameter on the 2captcha in.php endpoint.
METHOD_MAP: dict[str, str] = {
    "recaptchav2": "userrecaptcha",
    "recaptchav3": "userrecaptcha",
    "hcaptcha": "hcaptcha",
    "turnstile": "turnstile",
    "funcaptcha": "funcaptcha",
}


def _params_for(kind: CaptchaKind, *, sitekey: str, url: str, **extras: object) -> dict[str, Any]:
    params: dict[str, Any] = {
        "method": METHOD_MAP[kind],
        "pageurl": url,
        "json": 1,
    }
    if kind in ("recaptchav2", "recaptchav3", "turnstile"):
        params["sitekey"] = sitekey
    if kind == "hcaptcha":
        params["sitekey"] = sitekey
    if kind == "funcaptcha":
        params["publickey"] = sitekey
    if kind == "recaptchav3":
        params["version"] = "v3"
        params["action"] = extras.get("action", "submit")
        params["min_score"] = extras.get("min_score", 0.3)
    if kind == "turnstile":
        action = extras.get("action")
        cdata = extras.get("cdata")
        if action:
            params["action"] = action
        if cdata:
            params["data"] = cdata
    return params


class TwoCaptchaSolver:
    """2captcha-backed :class:`~.base.CaptchaSolver`."""

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
            raise CaptchaUnsolvable("2captcha requires an api_key")
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.poll_interval = poll_interval
        self.max_polls = max_polls
        self._owned_client = client is None
        self._client = client or httpx.Client(timeout=30.0)

    def solve(
        self,
        kind: CaptchaKind,
        sitekey: str,
        url: str,
        **extras: object,
    ) -> str:
        if kind not in METHOD_MAP:
            raise CaptchaUnsolvable(f"unsupported CAPTCHA kind: {kind!r}")
        params = _params_for(kind, sitekey=sitekey, url=url, **extras)
        params["key"] = self.api_key
        resp = self._client.post(f"{self.api_base}/in.php", data=params)
        resp.raise_for_status()
        data = resp.json() if "json" in resp.headers.get("content-type", "").lower() else _parse_legacy(resp.text)
        if isinstance(data, dict):
            status = int(data.get("status", 0))
            if status != 1:
                raise CaptchaUnsolvable(f"2captcha in.php failed: {data.get('request') or data}")
            request_id = str(data.get("request"))
        else:
            raise CaptchaUnsolvable(f"2captcha in.php unexpected body: {data!r}")

        for _ in range(self.max_polls):
            time.sleep(self.poll_interval)
            r = self._client.get(
                f"{self.api_base}/res.php",
                params={"key": self.api_key, "action": "get", "id": request_id, "json": 1},
            )
            r.raise_for_status()
            payload = r.json() if "json" in r.headers.get("content-type", "").lower() else _parse_legacy(r.text)
            if isinstance(payload, dict):
                status = int(payload.get("status", 0))
                request = payload.get("request") or ""
                if status == 1 and isinstance(request, str) and request:
                    return request
                if request == "CAPCHA_NOT_READY":
                    continue
                if isinstance(request, str) and request.startswith("ERROR"):
                    raise CaptchaUnsolvable(f"2captcha error: {request}")
            else:
                raise CaptchaUnsolvable(f"2captcha res.php unexpected body: {payload!r}")
        raise CaptchaUnsolvable("2captcha timeout")

    def close(self) -> None:
        if self._owned_client:
            self._client.close()


def _parse_legacy(text: str) -> dict[str, Any]:
    """Parse the legacy ``OK|TOKEN`` and ``ERROR_FOO`` line responses."""
    text = (text or "").strip()
    if text.startswith("OK|"):
        return {"status": 1, "request": text[3:]}
    if text == "CAPCHA_NOT_READY":
        return {"status": 0, "request": "CAPCHA_NOT_READY"}
    if text.startswith("ERROR"):
        return {"status": 0, "request": text}
    return {"status": 0, "request": text}
