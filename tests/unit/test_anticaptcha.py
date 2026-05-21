"""Tests for ``captcha.anticaptcha`` — task-type map + recaptcha v3 extras."""

from __future__ import annotations

from nexscout.captcha.anticaptcha import API_BASE, TASK_TYPE, AntiCaptchaSolver


def test_task_type_map_contains_all_kinds() -> None:
    for k in ("hcaptcha", "recaptchav2", "recaptchav3", "turnstile", "funcaptcha"):
        assert k in TASK_TYPE
        assert "Proxyless" in TASK_TYPE[k]


def test_solver_uses_anticaptcha_base() -> None:
    solver = AntiCaptchaSolver(api_key="k")
    assert solver.api_base == API_BASE


def test_build_task_recaptchav2() -> None:
    s = AntiCaptchaSolver(api_key="k")
    out = s._build_task("recaptchav2", sitekey="abc", url="https://x.com")
    assert out["type"] == "RecaptchaV2TaskProxyless"
    assert out["websiteKey"] == "abc"


def test_build_task_recaptchav3_with_extras() -> None:
    s = AntiCaptchaSolver(api_key="k")
    out = s._build_task("recaptchav3", sitekey="abc", url="x", action="login", min_score=0.7)
    assert out["pageAction"] == "login"
    assert out["minScore"] == 0.7


def test_build_task_turnstile_with_action_cdata() -> None:
    s = AntiCaptchaSolver(api_key="k")
    out = s._build_task("turnstile", sitekey="x", url="y", action="a1", cdata="c1")
    assert out["action"] == "a1"
    assert out["cdata"] == "c1"


def test_build_task_turnstile_no_extras() -> None:
    s = AntiCaptchaSolver(api_key="k")
    out = s._build_task("turnstile", sitekey="x", url="y")
    assert "action" not in out
    assert "cdata" not in out
