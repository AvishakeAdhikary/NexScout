"""TASK_TYPE map shape — verbatim per §15.3 / §15.5."""

from __future__ import annotations

import pytest

from nexscout.captcha.anticaptcha import TASK_TYPE as ANTI_TASK_TYPE
from nexscout.captcha.anticaptcha import AntiCaptchaSolver
from nexscout.captcha.capsolver import TASK_TYPE as CAPSOLVER_TASK_TYPE
from nexscout.captcha.capsolver import CapSolverSolver
from nexscout.captcha.twocaptcha import METHOD_MAP as TWOCAPTCHA_METHOD_MAP
from nexscout.captcha.twocaptcha import TwoCaptchaSolver
from nexscout.core.errors import CaptchaUnsolvable


def test_capsolver_task_type_map_is_verbatim() -> None:
    assert CAPSOLVER_TASK_TYPE == {
        "hcaptcha": "HCaptchaTaskProxyLess",
        "recaptchav2": "ReCaptchaV2TaskProxyLess",
        "recaptchav3": "ReCaptchaV3TaskProxyLess",
        "turnstile": "AntiTurnstileTaskProxyLess",
        "funcaptcha": "FunCaptchaTaskProxyLess",
    }


def test_anticaptcha_task_type_uses_lowercase_less() -> None:
    # anti-captcha.com differs from capsolver by case ("...Proxyless" vs "...ProxyLess").
    assert ANTI_TASK_TYPE == {
        "hcaptcha": "HCaptchaTaskProxyless",
        "recaptchav2": "RecaptchaV2TaskProxyless",
        "recaptchav3": "RecaptchaV3TaskProxyless",
        "turnstile": "TurnstileTaskProxyless",
        "funcaptcha": "FunCaptchaTaskProxyless",
    }


def test_twocaptcha_method_map_covers_every_kind() -> None:
    for kind in ("recaptchav2", "recaptchav3", "hcaptcha", "turnstile", "funcaptcha"):
        assert kind in TWOCAPTCHA_METHOD_MAP


def test_capsolver_build_task_recaptchav3_includes_action() -> None:
    solver = CapSolverSolver("k")
    task = solver._build_task("recaptchav3", sitekey="key", url="https://x", action="login")
    assert task["pageAction"] == "login"
    solver.close()


def test_capsolver_build_task_turnstile_with_action_and_cdata() -> None:
    solver = CapSolverSolver("k")
    task = solver._build_task("turnstile", sitekey="key", url="https://x", action="login", cdata="ctx")
    assert task["metadata"] == {"action": "login", "cdata": "ctx"}
    solver.close()


def test_capsolver_unsupported_kind_raises() -> None:
    solver = CapSolverSolver("k")
    with pytest.raises(CaptchaUnsolvable):
        solver.solve("nope", "x", "https://x")  # type: ignore[arg-type]
    solver.close()


def test_capsolver_requires_api_key() -> None:
    with pytest.raises(CaptchaUnsolvable):
        CapSolverSolver("")


def test_anticaptcha_inherits_capsolver_with_override() -> None:
    solver = AntiCaptchaSolver("k")
    task = solver._build_task("hcaptcha", sitekey="x", url="https://x")
    assert task["type"] == "HCaptchaTaskProxyless"
    solver.close()


def test_twocaptcha_requires_api_key() -> None:
    with pytest.raises(CaptchaUnsolvable):
        TwoCaptchaSolver("")
