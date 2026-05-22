"""Injection JS — verify each verbatim snippet and the token substitution."""

from __future__ import annotations

import pytest

from nexscout.captcha.inject import (
    FUNCAPTCHA_INJECT_JS,
    HCAPTCHA_INJECT_JS,
    INJECT_JS,
    RECAPTCHA_INJECT_JS,
    TURNSTILE_INJECT_JS,
    build_inject_script,
)
from nexscout.core.errors import CaptchaUnsolvable


def test_inject_map_covers_each_kind() -> None:
    assert INJECT_JS["recaptchav2"] is RECAPTCHA_INJECT_JS
    assert INJECT_JS["recaptchav3"] is RECAPTCHA_INJECT_JS
    assert INJECT_JS["hcaptcha"] is HCAPTCHA_INJECT_JS
    assert INJECT_JS["turnstile"] is TURNSTILE_INJECT_JS
    assert INJECT_JS["funcaptcha"] is FUNCAPTCHA_INJECT_JS


def test_each_snippet_uses_the_token_placeholder() -> None:
    for snippet in (
        RECAPTCHA_INJECT_JS,
        HCAPTCHA_INJECT_JS,
        TURNSTILE_INJECT_JS,
        FUNCAPTCHA_INJECT_JS,
    ):
        assert "'THE_TOKEN'" in snippet


def test_each_snippet_targets_expected_dom_field() -> None:
    assert "g-recaptcha-response" in RECAPTCHA_INJECT_JS
    assert "h-captcha-response" in HCAPTCHA_INJECT_JS
    assert "cf-turnstile-response" in TURNSTILE_INJECT_JS
    assert "FunCaptcha-Token" in FUNCAPTCHA_INJECT_JS


def test_recaptcha_snippet_walks_grecaptcha_clients() -> None:
    # The verbatim §15.4 reCAPTCHA snippet walks ___grecaptcha_cfg.clients.
    assert "___grecaptcha_cfg" in RECAPTCHA_INJECT_JS
    assert "clients" in RECAPTCHA_INJECT_JS


def test_build_inject_script_replaces_token_safely() -> None:
    token = "abc'def\"ghi\\jkl"  # tricky string with single quote, double quote, backslash
    script = build_inject_script("hcaptcha", token)
    # The original placeholder must be gone.
    assert "'THE_TOKEN'" not in script
    # The token JSON-encoded form must be present.
    assert '"abc\'def\\"ghi\\\\jkl"' in script


def test_build_inject_unknown_kind_raises() -> None:
    with pytest.raises(CaptchaUnsolvable):
        build_inject_script("nope", "x")  # type: ignore[arg-type]


def test_funcaptcha_snippet_calls_arkose_enforcement() -> None:
    assert "ArkoseEnforcement" in FUNCAPTCHA_INJECT_JS
