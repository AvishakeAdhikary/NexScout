"""Browser automation for application forms (Playwright, headless Chromium).

- Runs Playwright's sync API in a worker thread (the worker's Selector loop can't spawn
  subprocesses on Windows; see infrastructure/render.py).
- Every request the page makes passes an SSRF guard: public http(s) hosts only, plus explicitly
  allowed origins (the demo application site in dev/test).
- `fill_form` fills but never submits. `submit_form` re-discovers the form, re-plans with the same
  inputs, and refuses to submit if the plan differs from the one the user approved.
- CAPTCHAs and logins are reported as blockers; NexScout never solves or bypasses them.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from nexscout.domain.errors import ValidationFailed
from nexscout.domain.forms import (
    Applicant,
    FormField,
    FormPlan,
    detect_blocker,
    detect_confirmation,
    plan_form,
)
from nexscout.infrastructure.security.urls import check_outbound_url

NAV_TIMEOUT_MS = 30_000

_DISCOVER_JS = """
() => Array.from(document.querySelectorAll('input,textarea,select')).map((el) => {
  const id = el.id, name = el.getAttribute('name') || '';
  let label = '';
  if (id) { const l = document.querySelector('label[for="' + CSS.escape(id) + '"]');
            if (l) label = l.innerText; }
  if (!label && el.closest('label')) label = el.closest('label').innerText;
  if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || name;
  const key = id ? '#' + CSS.escape(id) : (name ? '[name="' + name + '"]' : '');
  const type = (el.getAttribute('type') || 'text').toLowerCase();
  const kind = el.tagName === 'TEXTAREA' ? 'textarea' : el.tagName === 'SELECT' ? 'select' : type;
  return {key, label: (label || '').trim(), kind, required: !!el.required, name};
}).filter((f) => f.key)
"""


def _origin(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


@dataclass
class Guard:
    """Decides which requests the page may make."""

    allowed_origins: frozenset[str] = frozenset()
    _cache: dict[str, bool] = field(default_factory=dict)

    def allows(self, url: str) -> bool:
        if url.startswith(("data:", "blob:", "about:")):
            return True
        origin = _origin(url)
        if origin in self.allowed_origins:
            return True
        if origin not in self._cache:
            try:
                check_outbound_url(url, allow_private=False, resolve=True)
                self._cache[origin] = True
            except ValidationFailed:
                self._cache[origin] = False
        return self._cache[origin]


@dataclass
class FillOutcome:
    status: str  # filled | blocked | missing | error
    url: str
    title: str = ""
    blocker: str | None = None
    plan: FormPlan | None = None
    screenshot: bytes | None = None
    error: str | None = None


@dataclass
class SubmitOutcome:
    clicked: bool
    confirmed: bool = False
    reference: str | None = None
    excerpt: str = ""
    final_url: str = ""
    screenshot: bytes | None = None
    error: str | None = None
    plan_changed: bool = False


def _open(p: Any, url: str, guard: Guard, headless: bool) -> tuple[Any, Any]:
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(accept_downloads=False)
    context.route(
        "**/*",
        lambda route: route.continue_() if guard.allows(route.request.url) else route.abort(),
    )
    page = context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    if not guard.allows(url):
        browser.close()
        raise PermissionError("That address points to a restricted network location.")
    page.goto(url, wait_until="load")
    return browser, page


def _discover(page: Any) -> tuple[list[FormField], str | None, str]:
    text = page.inner_text("body")[:20_000]
    raw = page.evaluate(_DISCOVER_JS)
    fields = [FormField(**r) for r in raw]
    has_password = any(f.kind == "password" for f in fields)
    frames = page.locator(
        "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], "
        ".g-recaptcha, .h-captcha, .cf-turnstile"
    ).count()
    return fields, detect_blocker(text, has_password, frames > 0), text


def _apply_plan(page: Any, plan: FormPlan) -> None:
    for f in plan.fields:
        if f.action == "fill" and f.value is not None:
            if f.kind == "select":
                page.select_option(f.key, label=f.value)
            else:
                page.fill(f.key, f.value)
        elif f.action == "upload" and f.value:
            page.set_input_files(f.key, f.value)


def _fill_sync(url: str, who: Applicant, guard: Guard, headless: bool) -> FillOutcome:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser, page = _open(p, url, guard, headless)
            try:
                fields, blocker, _ = _discover(page)
                title = page.title()
                if blocker:
                    return FillOutcome(
                        "blocked",
                        page.url,
                        title,
                        blocker=blocker,
                        screenshot=page.screenshot(full_page=True),
                    )
                plan = plan_form(fields, who)
                if plan.missing:
                    return FillOutcome(
                        "missing",
                        page.url,
                        title,
                        plan=plan,
                        screenshot=page.screenshot(full_page=True),
                    )
                _apply_plan(page, plan)
                return FillOutcome(
                    "filled", page.url, title, plan=plan, screenshot=page.screenshot(full_page=True)
                )
            finally:
                browser.close()
    except (PlaywrightError, PermissionError) as exc:
        return FillOutcome("error", url, error=str(exc).splitlines()[0][:300])


def _submit_sync(
    url: str, who: Applicant, approved_digest: str, guard: Guard, headless: bool
) -> SubmitOutcome:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    clicked = False
    try:
        with sync_playwright() as p:
            browser, page = _open(p, url, guard, headless)
            try:
                fields, blocker, _ = _discover(page)
                plan = plan_form(fields, who)
                if blocker or plan.missing or plan.digest() != approved_digest:
                    return SubmitOutcome(
                        clicked=False,
                        plan_changed=True,
                        error="The form changed since you approved it.",
                    )
                _apply_plan(page, plan)
                for f in plan.fields:
                    if f.action == "check_on_submit":
                        page.check(f.key)
                first = next(f for f in plan.fields if f.action in ("fill", "upload"))
                form = page.locator(f"form:has({first.key})").first
                button = form.locator("button[type=submit], input[type=submit], button:not([type])")
                clicked = True  # from here on, the outcome may be uncertain
                button.first.click()
                page.wait_for_load_state("load")
                text = page.inner_text("body")[:20_000]
                confirmed, ref = detect_confirmation(text)
                excerpt = " ".join(text.split())[:500]
                return SubmitOutcome(
                    True, confirmed, ref, excerpt, page.url, page.screenshot(full_page=True)
                )
            finally:
                browser.close()
    except (PlaywrightError, PermissionError, StopIteration) as exc:
        return SubmitOutcome(clicked=clicked, error=str(exc).splitlines()[0][:300] or "error")


@dataclass
class AssistOutcome:
    status: str  # confirmed | timeout | closed | error
    reference: str | None = None
    final_url: str = ""
    excerpt: str = ""
    screenshot: bytes | None = None
    error: str | None = None


# Tests stand in for the person at the keyboard: called with (page, "blocked" | "filled").
# Production leaves it unset; a real person solves the CAPTCHA and presses submit.
ASSIST_HUMAN: Callable[[Any, str], None] | None = None


def _assist_sync(
    url: str, who: Applicant, guard: Guard, headless: bool, timeout_s: float
) -> AssistOutcome:
    """Assisted mode: a visible browser window on the user's computer. NexScout fills what
    it knows; the person solves any CAPTCHA or sign-in, checks everything, ticks declarations
    and submits. NexScout only watches for the confirmation page. It never clicks submit and
    never touches the challenge."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    deadline = time.monotonic() + timeout_s
    try:
        with sync_playwright() as p:
            browser, page = _open(p, url, guard, headless)
            try:
                filled = False
                told_blocked = False
                while time.monotonic() < deadline:
                    if page.is_closed():
                        return AssistOutcome("closed")
                    try:
                        text = page.inner_text("body")[:20_000]
                        confirmed, ref = detect_confirmation(text)
                        if confirmed:
                            return AssistOutcome(
                                "confirmed",
                                ref,
                                page.url,
                                " ".join(text.split())[:500],
                                page.screenshot(full_page=True),
                            )
                        if not filled:
                            fields, blocker, _ = _discover(page)
                            if blocker:
                                if not told_blocked and ASSIST_HUMAN:
                                    ASSIST_HUMAN(page, "blocked")
                                told_blocked = True
                            elif fields:
                                _apply_plan(page, plan_form(fields, who))
                                filled = True
                                if ASSIST_HUMAN:
                                    ASSIST_HUMAN(page, "filled")
                    except PlaywrightError:
                        pass  # navigating (the person submitted or solved a challenge)
                    time.sleep(0.5)
                return AssistOutcome("timeout")
            finally:
                browser.close()
    except PlaywrightError as exc:
        msg = str(exc).splitlines()[0][:300]
        return AssistOutcome("closed" if "closed" in msg.lower() else "error", error=msg)
    except PermissionError as exc:
        return AssistOutcome("error", error=str(exc))


async def assist_form(
    url: str, who: Applicant, guard: Guard, *, headless: bool, timeout_s: float
) -> AssistOutcome:
    return await asyncio.to_thread(_assist_sync, url, who, guard, headless, timeout_s)


async def fill_form(
    url: str, who: Applicant, guard: Guard, *, headless: bool = True
) -> FillOutcome:
    return await asyncio.to_thread(_fill_sync, url, who, guard, headless)


async def submit_form(
    url: str, who: Applicant, approved_digest: str, guard: Guard, *, headless: bool = True
) -> SubmitOutcome:
    return await asyncio.to_thread(_submit_sync, url, who, approved_digest, guard, headless)
