"""Tests for ``apply.email_browser`` — Gmail browser-driven send."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexscout.apply.email_browser import (
    _build_compose_url,
    _click,
    _find_first,
    _safe_send_keys,
    _wait_for,
    send_via_gmail_browser,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_build_compose_url_url_encoded() -> None:
    url = _build_compose_url(to="a@b.com", subject="Hi there", body="line1\nline2")
    assert "to=a%40b.com" in url
    assert url.startswith("https://mail.google.com")


def test_safe_send_keys_clear_then_send() -> None:
    el = MagicMock()
    _safe_send_keys(el, "x")
    el.clear.assert_called_once()
    el.send_keys.assert_called_once_with("x")


def test_safe_send_keys_clear_failure_still_sends() -> None:
    el = MagicMock()
    el.clear.side_effect = RuntimeError("nope")
    _safe_send_keys(el, "x")
    el.send_keys.assert_called_once_with("x")


def test_click_helper_handles_exception() -> None:
    el = MagicMock()
    el.click.side_effect = RuntimeError("nope")
    _click(el)  # should not raise


def test_find_first_visible_element() -> None:
    visible = MagicMock()
    visible.is_displayed.return_value = True
    hidden = MagicMock()
    hidden.is_displayed.return_value = False

    drv = MagicMock()
    drv.find_elements.return_value = [hidden, visible]
    out = _find_first(drv, ["#x"])
    assert out is visible


def test_find_first_no_match() -> None:
    drv = MagicMock()
    drv.find_elements.return_value = []
    assert _find_first(drv, ["#x"]) is None


def test_find_first_handles_driver_exception() -> None:
    drv = MagicMock()
    drv.find_elements.side_effect = RuntimeError("nope")
    assert _find_first(drv, ["#x"]) is None


def test_find_first_is_displayed_raises() -> None:
    el = MagicMock()
    el.is_displayed.side_effect = RuntimeError("nope")
    drv = MagicMock()
    drv.find_elements.return_value = [el]
    # When `is_displayed` raises we still treat the element as visible.
    out = _find_first(drv, ["#x"])
    assert out is el


def test_wait_for_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    drv = MagicMock()
    drv.find_elements.return_value = []
    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)
    assert _wait_for(drv, ["#x"], timeout=0.05, poll=0.01) is None


# ---------------------------------------------------------------------------
# send_via_gmail_browser
# ---------------------------------------------------------------------------


def test_send_via_gmail_browser_missing_credentials() -> None:
    ok, _err = send_via_gmail_browser(
        driver=MagicMock(),
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[],
        user_email="",
        password="",
    )
    assert not ok


def test_send_via_gmail_browser_navigate_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    drv = MagicMock()
    drv.get.side_effect = RuntimeError("nav failed")
    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[],
        user_email="me@gmail.com",
        password="pw",
    )
    assert not ok
    assert "navigate failed" in (err or "")


def test_send_via_gmail_browser_full_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive the whole flow with all UI elements present."""
    attach = tmp_path / "cv.pdf"
    attach.write_bytes(b"%PDF")

    visible_el = MagicMock()
    visible_el.is_displayed.return_value = True

    drv = MagicMock()
    # Every find_elements returns the same visible element so each wait succeeds.
    drv.find_elements.return_value = [visible_el]

    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)
    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[str(attach)],
        user_email="me@gmail.com",
        password="pw",
        timeout=1.0,
    )
    assert ok, err


def test_send_via_gmail_browser_password_field_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the password field never appears after entering the email, we fail."""

    visible_el = MagicMock()
    visible_el.is_displayed.return_value = True

    # find_elements: first call sees email (visible_el), then nothing else for password.
    calls: list[str] = []

    def _find_elements(by: str, sel: str) -> list[Any]:
        calls.append(sel)
        # Return visible elements for the email selectors only.
        if "email" in sel or "identifier" in sel or sel == "#identifierNext button":
            return [visible_el]
        return []

    drv = MagicMock()
    drv.find_elements.side_effect = _find_elements

    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)

    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[],
        user_email="me@gmail.com",
        password="pw",
        timeout=0.05,
    )
    assert not ok
    assert err and "password" in err


def test_send_via_gmail_browser_attachment_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    visible_el = MagicMock()
    visible_el.is_displayed.return_value = True
    drv = MagicMock()
    drv.find_elements.return_value = [visible_el]

    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)
    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[str(tmp_path / "nope.pdf")],
        user_email="me@gmail.com",
        password="pw",
        timeout=0.5,
    )
    assert not ok
    assert err and "attachment missing" in err


def test_send_via_gmail_browser_no_compose_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the email field never appears AND the compose dialog never opens."""
    drv = MagicMock()
    drv.find_elements.return_value = []
    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)
    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[],
        user_email="me@gmail.com",
        password="pw",
        timeout=0.05,
    )
    assert not ok
    assert err and "compose" in err


def test_send_via_gmail_browser_send_button_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose dialog opens, but no Send button appears."""
    visible_el = MagicMock()
    visible_el.is_displayed.return_value = True
    drv = MagicMock()

    state = {"calls": 0}

    def _find_elements(by: str, sel: str) -> list[Any]:
        state["calls"] += 1
        if "Send" in sel or "aria-label^=\"Send\"" in sel or "data-tooltip" in sel:
            return []
        return [visible_el]

    drv.find_elements.side_effect = _find_elements
    monkeypatch.setattr("nexscout.apply.email_browser.time.sleep", lambda s: None)
    ok, err = send_via_gmail_browser(
        driver=drv,
        to="a@b.com",
        subject="x",
        body="y",
        attachments=[],
        user_email="me@gmail.com",
        password="pw",
        timeout=0.1,
    )
    assert not ok
    assert err and "Send button" in err
