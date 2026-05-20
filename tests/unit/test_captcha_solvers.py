"""Coverage tests for CapSolver / 2captcha / Anti-Captcha solver classes."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from nexscout.captcha.anticaptcha import AntiCaptchaSolver
from nexscout.captcha.capsolver import CapSolverSolver
from nexscout.captcha.capsolver import _extract_token as cap_extract
from nexscout.captcha.twocaptcha import TwoCaptchaSolver, _parse_legacy
from nexscout.core.errors import CaptchaUnsolvable

# ---------------------------------------------------------------------------
# Httpx mock helpers (build a transport that returns canned responses)
# ---------------------------------------------------------------------------


class _Stub:
    """Replace ``httpx.Client.post`` / ``.get`` with scripted responses."""

    def __init__(self, post_payloads: list[Any] | None = None, get_payloads: list[Any] | None = None) -> None:
        self.post_payloads = list(post_payloads or [])
        self.get_payloads = list(get_payloads or [])
        self.posts: list[dict[str, Any]] = []
        self.gets: list[dict[str, Any]] = []

    def post(self, url: str, **kw: Any) -> httpx.Response:
        self.posts.append({"url": url, **kw})
        body = self.post_payloads.pop(0)
        return _make_response(url, "POST", body)

    def get(self, url: str, **kw: Any) -> httpx.Response:
        self.gets.append({"url": url, **kw})
        body = self.get_payloads.pop(0)
        return _make_response(url, "GET", body)


def _make_response(url: str, method: str, body: Any) -> httpx.Response:
    if isinstance(body, dict):
        if "_status" in body:
            return httpx.Response(int(body["_status"]), json=body.get("json", {}), request=httpx.Request(method, url))
        return httpx.Response(200, json=body, request=httpx.Request(method, url))
    if isinstance(body, tuple):
        status, text = body
        return httpx.Response(int(status), text=text, request=httpx.Request(method, url))
    if isinstance(body, str):
        return httpx.Response(200, text=body, request=httpx.Request(method, url))
    raise AssertionError(f"unsupported stubbed body: {body!r}")


# ---------------------------------------------------------------------------
# CapSolver
# ---------------------------------------------------------------------------


class TestCapSolver:
    def test_solve_happy_path_recaptcha(self) -> None:
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "task-1"},
                {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOKEN"}},
            ]
        )
        s = CapSolverSolver(api_key="cap-key", client=stub, poll_interval=0)  # type: ignore[arg-type]
        assert s.solve("recaptchav2", sitekey="6Lc-x", url="https://x.com") == "TOKEN"
        # createTask body included the right type.
        body = stub.posts[0]["json"]
        assert body["task"]["type"] == "ReCaptchaV2TaskProxyLess"

    def test_solve_turnstile_with_metadata(self) -> None:
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "t-2"},
                {"errorId": 0, "status": "ready", "solution": {"token": "cf-token"}},
            ]
        )
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        out = s.solve("turnstile", sitekey="ts", url="https://x.com", action="submit", cdata="abc")
        assert out == "cf-token"
        body = stub.posts[0]["json"]
        assert body["task"]["metadata"] == {"action": "submit", "cdata": "abc"}

    def test_solve_recaptchav3_default_action(self) -> None:
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "t-3"},
                {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "T"}},
            ]
        )
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        s.solve("recaptchav3", sitekey="rc3", url="https://x.com")
        assert stub.posts[0]["json"]["task"]["pageAction"] == "submit"

    def test_solve_create_error_raises(self) -> None:
        stub = _Stub(post_payloads=[{"errorId": 7, "errorDescription": "bad key"}])
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="bad key"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_solve_unsupported_kind(self) -> None:
        s = CapSolverSolver(api_key="k", client=_Stub(), poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="unsupported"):
            s.solve("madeup", sitekey="x", url="https://x.com")  # type: ignore[arg-type]

    def test_solve_missing_task_id(self) -> None:
        stub = _Stub(post_payloads=[{"errorId": 0}])
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="no taskId"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_poll_timeout_raises(self) -> None:
        # Always returns processing, never ready.
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "t"},
                {"errorId": 0, "status": "processing"},
                {"errorId": 0, "status": "processing"},
            ]
        )
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0, max_polls=2)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="timeout"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_poll_error_id(self) -> None:
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "t"},
                {"errorId": 9, "errorDescription": "boom"},
            ]
        )
        s = CapSolverSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="boom"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_constructor_requires_key(self) -> None:
        with pytest.raises(CaptchaUnsolvable, match="api_key"):
            CapSolverSolver(api_key="")

    def test_extract_token_helpers(self) -> None:
        assert cap_extract("turnstile", {"token": "x"}) == "x"
        assert cap_extract("hcaptcha", {"gRecaptchaResponse": "y"}) == "y"
        with pytest.raises(CaptchaUnsolvable):
            cap_extract("hcaptcha", {})


# ---------------------------------------------------------------------------
# 2captcha
# ---------------------------------------------------------------------------


class TestTwoCaptcha:
    def test_solve_happy_path_json(self) -> None:
        stub = _Stub(
            post_payloads=[{"status": 1, "request": "req-1"}],
            get_payloads=[{"status": 1, "request": "FINAL-TOKEN"}],
        )
        # 2captcha responses are JSON because we set json=1 in params.
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        # The provider uses resp.headers["content-type"] to choose parser.
        # httpx.Response from json=... has application/json header by default.
        out = s.solve("recaptchav2", sitekey="rc2", url="https://x.com")
        assert out == "FINAL-TOKEN"

    def test_solve_legacy_text(self) -> None:
        stub = _Stub(
            post_payloads=[(200, "OK|123")],
            get_payloads=[(200, "OK|TOKEN-X")],
        )
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        out = s.solve("hcaptcha", sitekey="h", url="https://x.com")
        assert out == "TOKEN-X"

    def test_in_php_failure_raises(self) -> None:
        stub = _Stub(post_payloads=[{"status": 0, "request": "ERROR_KEY"}])
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="ERROR_KEY"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_unsupported_kind(self) -> None:
        s = TwoCaptchaSolver(api_key="k", client=_Stub(), poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="unsupported"):
            s.solve("madeup", sitekey="x", url="https://x.com")  # type: ignore[arg-type]

    def test_res_php_returns_error_string(self) -> None:
        stub = _Stub(
            post_payloads=[{"status": 1, "request": "req"}],
            get_payloads=[(200, "ERROR_BAD_DUPLICATES")],
        )
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="ERROR_BAD_DUPLICATES"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_polls_until_ready(self) -> None:
        stub = _Stub(
            post_payloads=[{"status": 1, "request": "req"}],
            get_payloads=[
                (200, "CAPCHA_NOT_READY"),
                {"status": 1, "request": "TOKEN-1"},
            ],
        )
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        assert s.solve("hcaptcha", sitekey="h", url="https://x.com") == "TOKEN-1"

    def test_solve_timeout(self) -> None:
        stub = _Stub(
            post_payloads=[{"status": 1, "request": "req"}],
            get_payloads=[(200, "CAPCHA_NOT_READY")] * 3,
        )
        s = TwoCaptchaSolver(api_key="k", client=stub, poll_interval=0, max_polls=2)  # type: ignore[arg-type]
        with pytest.raises(CaptchaUnsolvable, match="timeout"):
            s.solve("hcaptcha", sitekey="h", url="https://x.com")

    def test_constructor_requires_key(self) -> None:
        with pytest.raises(CaptchaUnsolvable):
            TwoCaptchaSolver(api_key="")

    def test_parse_legacy_variants(self) -> None:
        assert _parse_legacy("OK|abc") == {"status": 1, "request": "abc"}
        assert _parse_legacy("CAPCHA_NOT_READY")["status"] == 0
        assert _parse_legacy("ERROR_FOO")["status"] == 0
        assert _parse_legacy("")["status"] == 0


# ---------------------------------------------------------------------------
# Anti-Captcha (same shape as CapSolver)
# ---------------------------------------------------------------------------


class TestAntiCaptcha:
    def test_solve_uses_same_flow(self) -> None:
        stub = _Stub(
            post_payloads=[
                {"errorId": 0, "taskId": "a-1"},
                {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOK"}},
            ]
        )
        s = AntiCaptchaSolver(api_key="k", client=stub, poll_interval=0)  # type: ignore[arg-type]
        assert s.solve("recaptchav2", sitekey="rc", url="https://x.com") == "TOK"
