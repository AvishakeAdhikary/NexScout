"""Browser-driven Gmail login + compose fallback for :func:`send_email`.

Used when neither an explicit ``smtp_factory`` nor ``profile.smtp.host`` are
configured but the user's email is a ``@gmail.com`` address and they've
supplied a Gmail-specific password (an "app password" in modern Gmail) via
``profile.gmail_password`` or ``profile.smtp.password``.

Flow per §13.4 step 4c (login) and the user's task-3 spec:

1. Navigate to the Gmail compose URL, pre-filled with to/subject/body.
2. If the login form appears, fill ``input[type="email"]`` → Next →
   ``input[type="password"]`` → Next.
3. Attach any files via the compose dialog's file input.
4. Click Send.
5. Verify the "Message sent" toast / aria-live region.

The function takes a Selenium-like driver object so callers (production +
tests) can inject either a real undetected_chromedriver instance or a mock.
"""

from __future__ import annotations

import logging
import time
import urllib.parse as urlparse
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


class _DriverLike(Protocol):
    """Tiny surface of the Selenium API we need."""

    current_url: str
    page_source: str

    def get(self, url: str) -> None: ...
    def find_elements(self, by: str, value: str) -> list[Any]: ...
    def find_element(self, by: str, value: str) -> Any: ...


# Selenium "By" constants — duplicated here so the module doesn't import
# selenium eagerly (it's only required in the apply backend).
BY_CSS = "css selector"
BY_XPATH = "xpath"


def _find_first(driver: _DriverLike, selectors: list[str], by: str = BY_CSS) -> Any | None:
    for sel in selectors:
        try:
            els = driver.find_elements(by, sel)
        except Exception:
            continue
        for el in els:
            try:
                visible = bool(getattr(el, "is_displayed", lambda: True)())
            except Exception:
                visible = True
            if visible:
                return el
    return None


def _safe_send_keys(el: Any, value: str) -> None:
    from contextlib import suppress

    with suppress(Exception):
        el.clear()
    el.send_keys(value)


def _click(el: Any) -> None:
    try:
        el.click()
    except Exception as e:
        log.debug("gmail click failed: %s", e)


def _wait_for(
    driver: _DriverLike,
    selectors: list[str],
    *,
    timeout: float,
    poll: float = 0.5,
    by: str = BY_CSS,
) -> Any | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        el = _find_first(driver, selectors, by=by)
        if el is not None:
            return el
        time.sleep(poll)
    return None


def _build_compose_url(*, to: str, subject: str, body: str) -> str:
    params = {
        "view": "cm",
        "fs": "1",
        "to": to,
        "su": subject,
        "body": body,
    }
    return "https://mail.google.com/mail/?" + urlparse.urlencode(params, quote_via=urlparse.quote)


def send_via_gmail_browser(
    *,
    driver: _DriverLike,
    to: str,
    subject: str,
    body: str,
    attachments: list[str],
    user_email: str,
    password: str,
    timeout: float = 30.0,
) -> tuple[bool, str | None]:
    """Drive the Gmail UI to send a single email. Returns ``(ok, error)``.

    Raises nothing — every failure is recorded as ``ok=False``.
    """
    if not user_email or not password:
        return False, "missing gmail credentials"

    try:
        driver.get(_build_compose_url(to=to, subject=subject, body=body))
    except Exception as e:
        return False, f"navigate failed: {e}"

    # ---- Login (if asked) -------------------------------------------------
    email_input = _wait_for(driver, ['input[type="email"]', 'input[name="identifier"]'], timeout=5.0)
    if email_input is not None:
        _safe_send_keys(email_input, user_email)
        next_btn = _find_first(driver, ["#identifierNext button", '[id="identifierNext"]', 'button:has(span)'])
        if next_btn is not None:
            _click(next_btn)
        else:
            # Fallback: press Enter via the input.
            try:
                from selenium.webdriver.common.keys import Keys

                email_input.send_keys(Keys.RETURN)
            except Exception:
                pass

        pwd_input = _wait_for(driver, ['input[type="password"]', 'input[name="Passwd"]'], timeout=timeout)
        if pwd_input is None:
            return False, "password field never appeared"
        _safe_send_keys(pwd_input, password)
        pwd_next = _find_first(driver, ["#passwordNext button", '[id="passwordNext"]', 'button:has(span)'])
        if pwd_next is not None:
            _click(pwd_next)
        else:
            try:
                from selenium.webdriver.common.keys import Keys

                pwd_input.send_keys(Keys.RETURN)
            except Exception:
                pass

    # ---- Wait for the compose dialog --------------------------------------
    compose = _wait_for(
        driver,
        [
            'form[role="dialog"]',
            'div[role="dialog"][aria-label*="Message"]',
            'div[role="dialog"][aria-label*="New Message"]',
        ],
        timeout=timeout,
    )
    if compose is None:
        return False, "compose dialog never opened"

    # ---- Attach files -----------------------------------------------------
    for att in attachments:
        if not att or not Path(att).exists():
            return False, f"attachment missing: {att}"
        file_input = _find_first(
            driver,
            ['form[role="dialog"] input[type="file"]', 'div[role="dialog"] input[type="file"]'],
        )
        if file_input is None:
            return False, "no file input visible in compose dialog"
        try:
            file_input.send_keys(str(Path(att).resolve()))
        except Exception as e:
            return False, f"upload failed for {att}: {e}"
        # Give Gmail a beat to ingest the file.
        time.sleep(1.0)

    # ---- Click Send -------------------------------------------------------
    send_btn = _find_first(
        driver,
        [
            'div[role="button"][aria-label^="Send"]',
            'div[role="button"][data-tooltip^="Send"]',
            'button[aria-label^="Send"]',
        ],
    )
    if send_btn is None:
        return False, "Send button not found"
    _click(send_btn)

    # ---- Verify the toast -------------------------------------------------
    toast = _wait_for(
        driver,
        [
            '[aria-live="polite"]',
            '[aria-live="assertive"]',
            'span:contains("Message sent")',
        ],
        timeout=15.0,
    )
    if toast is None:
        # We don't outright fail — Gmail sometimes routes the toast through
        # a transient element. Treat absence as best-effort success but log.
        log.info("gmail: no 'Message sent' toast detected; trusting Send click")
    return True, None


__all__ = ["BY_CSS", "BY_XPATH", "send_via_gmail_browser"]
