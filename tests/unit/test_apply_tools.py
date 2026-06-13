"""Tests for ``apply.tools`` — the 12 ReAct tools + dispatch + helpers."""

from __future__ import annotations

import smtplib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexscout.apply import tools
from nexscout.apply.tools import (
    ToolResult,
    _build_email_message,
    _shrink_for_log,
    _smtp_factory_from_profile,
    append_transcript,
    click,
    dispatch_tool,
    done,
    fill_form,
    get_tool_specs,
    navigate,
    read_page,
    screenshot,
    select,
    send_email,
    simplify_dom,
    solve_captcha,
    tabs,
    upload,
    wait,
)
from nexscout.core.errors import CaptchaUnsolvable


def _profile_smtp(**overrides: Any) -> SimpleNamespace:
    base = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "me",
        "password": "pw",
        "use_ssl": False,
        "use_tls": True,
    }
    base.update(overrides)
    smtp = SimpleNamespace(**base)
    return SimpleNamespace(smtp=smtp, me=SimpleNamespace(email="me@example.com"))


# ---------------------------------------------------------------------------
# simplify_dom
# ---------------------------------------------------------------------------


def test_simplify_dom_empty() -> None:
    assert simplify_dom("") == ""


def test_simplify_dom_strips_head_scripts_styles_and_class_too_long() -> None:
    html = """
    <html><head><title>X</title><script>alert(1)</script></head>
    <body>
      <div class="this-class-is-way-too-long-and-should-be-dropped" id="hi" data-testid="card">
        <span class="short" aria-label="Read more" role="button">A</span>
        <style>.x{}</style>
        <noscript>noop</noscript>
        <iframe src="x"></iframe>
        <link rel="x">
      </div>
    </body></html>
    """
    out = simplify_dom(html)
    assert "<script" not in out
    assert "<style" not in out
    assert "<noscript" not in out
    assert "<iframe" not in out
    assert "<link" not in out
    assert "<head" not in out
    assert "this-class-is-way-too-long" not in out
    assert 'class="short"' in out
    assert "data-testid=" in out
    assert "aria-label=" in out
    assert 'role="button"' in out
    assert 'id="hi"' in out


def test_simplify_dom_keeps_short_class_attribute() -> None:
    out = simplify_dom('<a class="btn primary" href="/x">click</a>')
    assert "btn primary" in out
    assert 'href="/x"' in out


# ---------------------------------------------------------------------------
# _shrink_for_log
# ---------------------------------------------------------------------------


def test_shrink_for_log_truncates_strings() -> None:
    out = _shrink_for_log("a" * 5000)
    assert "truncated" in out


def test_shrink_for_log_bytes() -> None:
    assert _shrink_for_log(b"\x00\x01\x02") == "<3 bytes>"


def test_shrink_for_log_list_truncates_above_50() -> None:
    out = _shrink_for_log(list(range(100)))
    assert isinstance(out, list)
    assert len(out) == 51  # 50 items + tail message
    assert "truncated" in str(out[-1])


def test_shrink_for_log_recurses_into_dict() -> None:
    out = _shrink_for_log({"k": "a" * 5000})
    assert "truncated" in out["k"]


# ---------------------------------------------------------------------------
# navigate
# ---------------------------------------------------------------------------


def test_navigate_missing_url() -> None:
    drv = MagicMock()
    r = navigate(drv, {}, Path("/tmp"))
    assert not r.ok
    assert "missing url" in (r.error or "")


def test_navigate_success() -> None:
    drv = MagicMock()
    r = navigate(drv, {"url": "https://x.com"}, Path("/tmp"))
    assert r.ok
    drv.get.assert_called_once_with("https://x.com")


def test_navigate_handles_driver_exception() -> None:
    drv = MagicMock()
    drv.get.side_effect = RuntimeError("boom")
    r = navigate(drv, {"url": "https://x.com"}, Path("/tmp"))
    assert not r.ok
    assert "boom" in (r.error or "")


# ---------------------------------------------------------------------------
# read_page
# ---------------------------------------------------------------------------


def test_read_page_returns_simplified_html() -> None:
    drv = SimpleNamespace(
        page_source="<html><body><a href='/x'>x</a></body></html>",
        current_url="https://x.com",
        title="X",
    )
    r = read_page(drv, {}, Path("/tmp"))
    assert r.ok
    assert "<a" in r.data["html"]
    assert r.data["url"] == "https://x.com"


def test_read_page_handles_page_source_exception() -> None:
    class _Bad:
        @property
        def page_source(self) -> str:
            raise RuntimeError("nope")

    r = read_page(_Bad(), {}, Path("/tmp"))
    assert not r.ok


# ---------------------------------------------------------------------------
# screenshot
# ---------------------------------------------------------------------------


def test_screenshot_writes_under_bundle(tmp_path: Path) -> None:
    drv = MagicMock()
    drv.save_screenshot.return_value = True
    r = screenshot(drv, {"name": "login page"}, tmp_path, idx=7)
    assert r.ok
    assert "007_login_page.png" in r.data["path"]
    assert (tmp_path / "screenshots").exists()


def test_screenshot_failure() -> None:
    drv = MagicMock()
    drv.save_screenshot.side_effect = RuntimeError("disk full")
    r = screenshot(drv, {"name": "bad"}, Path("/tmp"))
    assert not r.ok


# ---------------------------------------------------------------------------
# click / fill_form / select / upload
# ---------------------------------------------------------------------------


def test_click_missing_ref() -> None:
    r = click(MagicMock(), {}, Path("/tmp"))
    assert not r.ok


def test_click_dispatches_to_form_filler(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.apply import form_filler

    monkeypatch.setattr(form_filler, "click", lambda d, r: True)
    r = click(MagicMock(), {"ref": "#submit"}, Path("/tmp"))
    assert r.ok


def test_fill_form_rejects_non_dict() -> None:
    r = fill_form(MagicMock(), {"fields": "not-a-dict"}, Path("/tmp"))
    assert not r.ok


def test_fill_form_aggregates_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.apply import form_filler

    monkeypatch.setattr(form_filler, "fill_form", lambda d, fields: {k: True for k in fields})
    r = fill_form(MagicMock(), {"fields": {"#name": "Jane"}}, Path("/tmp"))
    assert r.ok


def test_fill_form_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.apply import form_filler

    monkeypatch.setattr(form_filler, "fill_form", lambda d, fields: {"#a": True, "#b": False})
    r = fill_form(MagicMock(), {"fields": {"#a": "x", "#b": "y"}}, Path("/tmp"))
    assert not r.ok


def test_select_calls_form_filler(monkeypatch: pytest.MonkeyPatch) -> None:
    from nexscout.apply import form_filler

    monkeypatch.setattr(form_filler, "select_option", lambda d, r, v: True)
    out = select(MagicMock(), {"ref": "#country", "value": "USA"}, Path("/tmp"))
    assert out.ok


def test_upload_missing_file() -> None:
    r = upload(MagicMock(), {"ref": "#cv", "path": "/no/such/file"}, Path("/tmp"))
    assert not r.ok


def test_upload_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "cv.pdf"
    f.write_bytes(b"%PDF")
    from nexscout.apply import form_filler

    monkeypatch.setattr(form_filler, "upload", lambda d, r, p: True)
    out = upload(MagicMock(), {"ref": "#cv", "path": str(f)}, Path("/tmp"))
    assert out.ok


# ---------------------------------------------------------------------------
# tabs
# ---------------------------------------------------------------------------


def test_tabs_list() -> None:
    drv = SimpleNamespace(
        window_handles=["h1", "h2"],
        current_window_handle="h1",
    )
    r = tabs(drv, {"action": "list"}, Path("/tmp"))
    assert r.ok
    assert r.data["count"] == 2


def test_tabs_select_valid() -> None:
    switch = MagicMock()
    drv = SimpleNamespace(
        window_handles=["h1", "h2"],
        switch_to=SimpleNamespace(window=switch),
    )
    r = tabs(drv, {"action": "select", "idx": 1}, Path("/tmp"))
    assert r.ok
    switch.assert_called_once_with("h2")


def test_tabs_select_out_of_range() -> None:
    drv = SimpleNamespace(
        window_handles=["h1"],
        switch_to=SimpleNamespace(window=MagicMock()),
    )
    r = tabs(drv, {"action": "select", "idx": 5}, Path("/tmp"))
    assert not r.ok


def test_tabs_unknown_action() -> None:
    drv = SimpleNamespace(window_handles=[])
    r = tabs(drv, {"action": "nope"}, Path("/tmp"))
    assert not r.ok


def test_tabs_list_handles_driver_error() -> None:
    class _Bad:
        @property
        def window_handles(self) -> list[str]:
            raise RuntimeError("driver dead")

    r = tabs(_Bad(), {"action": "list"}, Path("/tmp"))
    assert not r.ok


# ---------------------------------------------------------------------------
# solve_captcha
# ---------------------------------------------------------------------------


def test_solve_captcha_no_solver_no_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.apply.tools.detect_in_driver", lambda d: None)
    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=None)
    assert r.ok
    assert r.data["detected"] is None


def test_solve_captcha_no_solver_manual_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "abc", "url": "x"},
    )
    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=None)
    assert not r.ok
    assert r.error == "captcha_manual_required"


def test_solve_captcha_solver_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "abc", "url": "x"},
    )
    monkeypatch.setattr("nexscout.apply.tools.inject_token", lambda d, k, t: None)

    class _S:
        def solve(self, kind: str, sk: str, url: str, **extras: Any) -> str:
            return "tok-1"

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert r.ok
    assert r.data["injected"]


def test_solve_captcha_unsolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "abc", "url": "x"},
    )

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            raise CaptchaUnsolvable("nope")

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert not r.ok
    assert "nope" in (r.error or "")


def test_solve_captcha_inject_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "abc", "url": "x"},
    )

    def _boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("inject crashed")

    monkeypatch.setattr("nexscout.apply.tools.inject_token", _boom)

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            return "tok"

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert not r.ok
    assert "inject" in (r.error or "")


def test_solve_captcha_unsupported_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "turnstile_script_only", "sitekey": "x", "url": "y"},
    )

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            return "x"

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert not r.ok


def test_solve_captcha_solver_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.tools.detect_in_driver",
        lambda d: {"type": "recaptcha", "sitekey": "abc", "url": "x"},
    )

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            raise ValueError("api down")

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert not r.ok
    assert "api down" in (r.error or "")


def test_solve_captcha_with_solver_no_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexscout.apply.tools.detect_in_driver", lambda d: None)

    class _S:
        def solve(self, *a: Any, **kw: Any) -> str:
            return "x"

    r = solve_captcha(MagicMock(), {}, Path("/tmp"), solver=_S())  # type: ignore[arg-type]
    assert r.ok
    assert r.data["detected"] is None


# ---------------------------------------------------------------------------
# send_email
# ---------------------------------------------------------------------------


def test_send_email_missing_to_subject() -> None:
    r = send_email(MagicMock(), {}, Path("/tmp"))
    assert not r.ok


def test_send_email_missing_attachment(tmp_path: Path) -> None:
    r = send_email(
        MagicMock(),
        {
            "to": "a@b.com",
            "subject": "x",
            "body": "y",
            "attachments": [str(tmp_path / "nope.pdf")],
        },
        Path("/tmp"),
    )
    assert not r.ok


def test_send_email_via_smtp_factory_success(tmp_path: Path) -> None:
    sent: list[Any] = []

    class _Client:
        def send_message(self, msg: Any) -> None:
            sent.append(msg)

        def quit(self) -> None:
            return None

    r = send_email(
        MagicMock(),
        {"to": "a@b.com", "subject": "Hello", "body": "Hi"},
        Path("/tmp"),
        smtp_factory=_Client,
    )
    assert r.ok
    assert sent


def test_send_email_via_smtp_factory_attachment_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "cv.pdf"
    f.write_bytes(b"%PDF")

    def _bad_build(*a: Any, **kw: Any) -> Any:
        raise OSError("disk")

    monkeypatch.setattr("nexscout.apply.tools._build_email_message", _bad_build)

    r = send_email(
        MagicMock(),
        {"to": "a@b.com", "subject": "x", "body": "y", "attachments": [str(f)]},
        Path("/tmp"),
        smtp_factory=MagicMock,
    )
    assert not r.ok
    assert "attachment failed" in (r.error or "")


def test_send_email_smtp_exception() -> None:
    class _BadClient:
        def send_message(self, m: Any) -> None:
            raise smtplib.SMTPException("auth failed")

        def quit(self) -> None:
            return None

    r = send_email(
        MagicMock(),
        {"to": "a@b.com", "subject": "x", "body": "y"},
        Path("/tmp"),
        smtp_factory=_BadClient,
    )
    assert not r.ok
    assert "smtp error" in (r.error or "")


def test_send_email_profile_smtp_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **kw: fake_client)
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **kw: fake_client)

    profile = _profile_smtp()
    r = send_email(
        MagicMock(),
        {"to": "a@b.com", "subject": "x", "body": "y"},
        Path("/tmp"),
        profile=profile,
    )
    assert r.ok
    fake_client.send_message.assert_called_once()


def test_send_email_profile_smtp_ssl_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *a, **kw: fake_client)
    profile = _profile_smtp(use_ssl=True, use_tls=False, port=465)
    r = send_email(
        MagicMock(),
        {"to": "a@b.com", "subject": "x", "body": "y"},
        Path("/tmp"),
        profile=profile,
    )
    assert r.ok


def test_send_email_no_transport() -> None:
    profile = SimpleNamespace(smtp=SimpleNamespace(host=""), me=SimpleNamespace(email="me@not-gmail.com"))
    r = send_email(MagicMock(), {"to": "a@b.com", "subject": "x", "body": "y"}, Path("/tmp"), profile=profile)
    assert not r.ok
    assert "no email transport" in (r.error or "")


def test_send_email_gmail_browser_path(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[Any] = []

    def _fake_send(**kw: Any) -> tuple[bool, str | None]:
        sent.append(kw)
        return True, None

    monkeypatch.setattr("nexscout.apply.email_browser.send_via_gmail_browser", _fake_send)
    profile = SimpleNamespace(
        smtp=SimpleNamespace(host=""),
        me=SimpleNamespace(email="me@gmail.com"),
        gmail_password="app-pw",
    )
    r = send_email(MagicMock(), {"to": "a@b.com", "subject": "x", "body": "y"}, Path("/tmp"), profile=profile)
    assert r.ok
    assert sent


def test_send_email_gmail_browser_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexscout.apply.email_browser.send_via_gmail_browser",
        lambda **kw: (False, "boom"),
    )
    profile = SimpleNamespace(
        smtp=SimpleNamespace(host=""),
        me=SimpleNamespace(email="me@gmail.com"),
        gmail_password="app-pw",
    )
    r = send_email(MagicMock(), {"to": "a@b.com", "subject": "x", "body": "y"}, Path("/tmp"), profile=profile)
    assert not r.ok


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------


def test_smtp_factory_from_profile_none() -> None:
    profile = SimpleNamespace(smtp=None)
    assert _smtp_factory_from_profile(profile) is None
    profile2 = SimpleNamespace(smtp=SimpleNamespace(host=""))
    assert _smtp_factory_from_profile(profile2) is None


def test_smtp_factory_from_profile_built(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = _profile_smtp()
    fac = _smtp_factory_from_profile(profile)
    assert fac is not None
    # Patch smtplib so the call doesn't try to talk to a real server.
    fake = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **kw: fake)
    fac()
    fake.starttls.assert_called_once()
    fake.login.assert_called_once()


def test_build_email_message_with_attachment(tmp_path: Path) -> None:
    f = tmp_path / "cv.pdf"
    f.write_bytes(b"%PDF")
    msg = _build_email_message(to="a@b.com", subject="x", body="y", attachments=[str(f)])
    assert msg["To"] == "a@b.com"
    assert msg["Subject"] == "x"


# ---------------------------------------------------------------------------
# wait / done
# ---------------------------------------------------------------------------


def test_wait_clamps_to_30s() -> None:
    r = wait(MagicMock(), {"ms": 99999}, Path("/tmp"))
    assert r.ok
    assert r.data["slept_ms"] == 30_000


def test_wait_clamps_negative() -> None:
    r = wait(MagicMock(), {"ms": -50}, Path("/tmp"))
    assert r.ok
    assert r.data["slept_ms"] == 0


def test_wait_bad_type() -> None:
    r = wait(MagicMock(), {"ms": "abc"}, Path("/tmp"))
    assert not r.ok


def test_done_parses_result_line() -> None:
    r = done(MagicMock(), {"result": "RESULT:APPLIED", "reason": "ok"}, Path("/tmp"))
    assert r.ok
    assert r.data["code"] == "APPLIED"
    assert r.data["reason"] == "ok"


def test_done_adds_prefix() -> None:
    r = done(MagicMock(), {"result": "APPLIED"}, Path("/tmp"))
    assert r.ok
    assert r.data["code"] == "APPLIED"


def test_done_missing_result() -> None:
    r = done(MagicMock(), {}, Path("/tmp"))
    assert not r.ok


def test_done_uses_status_synonym() -> None:
    r = done(MagicMock(), {"status": "APPLIED"}, Path("/tmp"))
    assert r.ok


# ---------------------------------------------------------------------------
# dispatch_tool
# ---------------------------------------------------------------------------


def test_dispatch_unknown_tool() -> None:
    r = dispatch_tool("does_not_exist", {}, driver=MagicMock(), bundle_dir=Path("/tmp"))
    assert not r.ok
    assert "unknown tool" in (r.error or "")


def test_dispatch_routes_each_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Every TOOL_NAMES routes to a real handler."""
    drv = MagicMock()
    drv.save_screenshot.return_value = True
    drv.page_source = "<html></html>"
    drv.current_url = ""
    drv.title = ""
    drv.window_handles = []
    drv.switch_to = SimpleNamespace(window=MagicMock())
    drv.find_element = MagicMock()

    monkeypatch.setattr("nexscout.apply.tools.detect_in_driver", lambda d: None)
    monkeypatch.setattr("nexscout.apply.form_filler.click", lambda d, r: True)
    monkeypatch.setattr("nexscout.apply.form_filler.fill_form", lambda d, f: {k: True for k in f})
    monkeypatch.setattr("nexscout.apply.form_filler.select_option", lambda d, r, v: True)
    monkeypatch.setattr("nexscout.apply.form_filler.upload", lambda d, r, p: True)

    f = tmp_path / "cv.pdf"
    f.write_bytes(b"x")

    for name in tools.TOOL_NAMES:
        args: dict[str, Any] = {}
        if name == "navigate":
            args["url"] = "https://x.com"
        elif name == "screenshot":
            args["name"] = "ok"
        elif name == "click":
            args["ref"] = "#x"
        elif name == "fill_form":
            args["fields"] = {"#x": "y"}
        elif name == "select":
            args["ref"] = "#x"
            args["value"] = "v"
        elif name == "upload":
            args["ref"] = "#x"
            args["path"] = str(f)
        elif name == "tabs":
            args["action"] = "list"
        elif name == "send_email":
            args["to"] = "a@b.com"
            args["subject"] = "x"
        elif name == "wait":
            args["ms"] = 0
        elif name == "done":
            args["result"] = "RESULT:APPLIED"

        r = dispatch_tool(name, args, driver=drv, bundle_dir=tmp_path)
        assert isinstance(r, ToolResult), f"{name} did not return ToolResult"


def test_get_tool_specs_has_thirteen_tools() -> None:
    specs = get_tool_specs()
    assert len(specs) == 13  # 12 originals + autofill
    names = {s["name"] for s in specs}
    assert names == set(tools.TOOL_NAMES)
    assert "autofill" in names


def test_match_profile_value() -> None:
    from types import SimpleNamespace

    from nexscout.apply.tools import match_profile_value

    prof = SimpleNamespace(
        me=SimpleNamespace(
            legal="Jane Doe",
            pref="Jane",
            email="jane@x.com",
            phone="123",
            links=SimpleNamespace(li="linkedin.com/in/jane", gh="github.com/jane"),
        )
    )
    assert match_profile_value({"type": "email", "name": "email"}, prof) == "jane@x.com"
    assert match_profile_value({"name": "phone"}, prof) == "123"
    assert match_profile_value({"label": "First Name"}, prof) == "Jane"
    assert match_profile_value({"label": "Last Name"}, prof) == "Doe"
    assert match_profile_value({"label": "Full name"}, prof) == "Jane Doe"
    assert match_profile_value({"name": "linkedin_url"}, prof) == "linkedin.com/in/jane"
    # NOT a person-name field — must stay None.
    assert match_profile_value({"label": "Company name"}, prof) is None
    assert match_profile_value({"name": "favourite_color"}, prof) is None


def test_autofill_fills_standard_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from nexscout.apply.tools import autofill

    prof = SimpleNamespace(
        me=SimpleNamespace(
            legal="Jane Doe", pref="Jane", email="jane@x.com", phone="123",
            links=SimpleNamespace(li="li", gh="gh"),
        )
    )
    fields = [
        {"type": "email", "name": "email", "label": "Email"},
        {"type": "text", "id": "phone", "label": "Phone"},
        {"type": "file", "name": "resume", "label": "Resume"},
        {"type": "text", "name": "company", "label": "Company"},
    ]
    drv = MagicMock()
    drv.execute_script.return_value = fields
    filled: dict[str, Any] = {}
    monkeypatch.setattr("nexscout.apply.form_filler.fill_input", lambda d, r, v: bool(filled.__setitem__(r, v)) or True)
    monkeypatch.setattr("nexscout.apply.form_filler.upload", lambda d, r, p: bool(filled.__setitem__(r, p)) or True)
    (tmp_path / "resume.pdf").write_bytes(b"x")

    r = autofill(drv, {}, tmp_path, prof)
    assert r.ok
    assert r.data["count"] == 3  # email + phone + resume (company is skipped)
    assert "jane@x.com" in filled.values()


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


def test_append_transcript_writes_line(tmp_path: Path) -> None:
    append_transcript(tmp_path, {"a": 1})
    append_transcript(tmp_path, {"b": 2})
    lines = (tmp_path / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
