"""Verify the verbatim §15.1 detect JS constant shape and helper logic."""

from __future__ import annotations

from typing import Any

from nexscout.captcha.detect import DETECT_JS, detect_in_driver


def test_detect_js_targets_every_captcha_family() -> None:
    # The §15.1 script must look for hCaptcha first, then Turnstile, then
    # reCAPTCHA v3, then v2, then FunCaptcha.
    assert ".h-captcha" in DETECT_JS
    assert "data-hcaptcha-sitekey" in DETECT_JS
    assert ".cf-turnstile" in DETECT_JS
    assert "challenges.cloudflare.com" in DETECT_JS
    # reCAPTCHA v3 detection via render= param.
    assert "render=" in DETECT_JS
    assert ".g-recaptcha" in DETECT_JS
    assert "FunCaptcha" in DETECT_JS
    assert "arkoselabs" in DETECT_JS


def test_detect_js_emits_turnstile_script_only_when_only_script_loaded() -> None:
    assert "turnstile_script_only" in DETECT_JS
    assert "Wait 3s and re-detect." in DETECT_JS


def test_detect_js_returns_url_in_result() -> None:
    # The script always sets r.url before returning.
    assert "r.url = url" in DETECT_JS


class _StubDriver:
    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.scripts: list[str] = []

    def execute_script(self, script: str, *args: Any) -> Any:
        self.scripts.append(script)
        return self._results.pop(0) if self._results else None


def test_detect_in_driver_returns_first_result() -> None:
    driver = _StubDriver([{"type": "hcaptcha", "sitekey": "k", "url": "https://x"}])
    out = detect_in_driver(driver)
    assert out is not None
    assert out["type"] == "hcaptcha"


def test_detect_in_driver_reruns_on_turnstile_script_only() -> None:
    first = {"type": "turnstile_script_only", "note": "Wait 3s and re-detect."}
    second = {"type": "turnstile", "sitekey": "k", "url": "https://x"}
    driver = _StubDriver([first, second])
    out = detect_in_driver(driver, sleep=0.0)
    assert out == second
    assert len(driver.scripts) == 2


def test_detect_in_driver_returns_none_when_no_match() -> None:
    driver = _StubDriver([None])
    assert detect_in_driver(driver) is None
