"""ATS form-filling heuristics shared by the agent tools.

These helpers are intentionally driver-agnostic — every entry point takes a
``driver`` that quacks like a Selenium WebDriver (``find_element``,
``execute_script``). Tests inject fakes.

Reference shapes used by the agent:

* ``ref`` may be a CSS selector, an XPath beginning with ``//``, a
  ``[data-testid=…]`` block, or a bare ``id``.
* ``value`` is always a string. Booleans are coerced to ``"true"`` / ``"false"``
  for select/checkbox semantics.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import Any, Protocol

log = logging.getLogger(__name__)


class _DriverLike(Protocol):
    def find_element(self, by: str, value: str) -> Any: ...

    def find_elements(self, by: str, value: str) -> list[Any]: ...

    def execute_script(self, script: str, *args: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Element location
# ---------------------------------------------------------------------------


def parse_ref(ref: str) -> tuple[str, str]:
    """Return a ``(by, value)`` pair Selenium's ``find_element`` accepts."""
    r = ref.strip()
    if not r:
        return ("css selector", "*")
    if r.startswith(("//", "(./")):
        return ("xpath", r)
    if r.startswith("#") and " " not in r and "[" not in r:
        return ("css selector", r)
    if r.startswith("."):
        return ("css selector", r)
    if r.startswith("["):
        return ("css selector", r)
    if r.startswith("id="):
        return ("css selector", f"#{r[3:]}")
    if r.startswith("name="):
        return ("css selector", f'[name="{r[5:]}"]')
    return ("css selector", r)


def find_one(driver: _DriverLike, ref: str) -> Any | None:
    by, value = parse_ref(ref)
    try:
        return driver.find_element(by, value)
    except Exception as e:
        log.debug("find_one failed for %s: %s", ref, e)
        return None


# ---------------------------------------------------------------------------
# Field-filling primitives
# ---------------------------------------------------------------------------


def _coerce_value(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return ""
    return str(value)


def _clear_then_send(el: Any, value: str) -> None:
    with suppress(Exception):
        el.clear()
    el.send_keys(value)


def fill_input(driver: _DriverLike, ref: str, value: Any) -> bool:
    """Type ``value`` into the first matching element. Returns success."""
    el = find_one(driver, ref)
    if el is None:
        return False
    v = _coerce_value(value)
    tag = (getattr(el, "tag_name", "") or "").lower()
    typ = ""
    with suppress(Exception):
        typ = (el.get_attribute("type") or "").lower()

    if tag == "select":
        return select_option(driver, ref, v)
    if typ == "checkbox":
        return set_checkbox(driver, ref, v not in {"", "false", "0", "no"})
    if typ == "radio":
        return click(driver, ref)

    try:
        _clear_then_send(el, v)
        return True
    except Exception as e:
        log.debug("fill_input fallback for %s: %s", ref, e)
        return _set_via_js(driver, ref, v)


def _set_via_js(driver: _DriverLike, ref: str, value: str) -> bool:
    """Last-ditch JS setter (handles React controlled-input weirdness)."""
    by, sel = parse_ref(ref)
    if by != "css selector":
        return False
    try:
        driver.execute_script(
            (
                "const el = document.querySelector(arguments[0]);"
                " if (!el) return false;"
                " const proto = Object.getPrototypeOf(el);"
                " const setter = Object.getOwnPropertyDescriptor(proto, 'value');"
                " if (setter && setter.set) setter.set.call(el, arguments[1]);"
                " else el.value = arguments[1];"
                " el.dispatchEvent(new Event('input',{bubbles:true}));"
                " el.dispatchEvent(new Event('change',{bubbles:true}));"
                " return true;"
            ),
            sel,
            value,
        )
        return True
    except Exception as e:
        log.debug("JS setter failed for %s: %s", ref, e)
        return False


def select_option(driver: _DriverLike, ref: str, value: str) -> bool:
    """Open ``<select>`` (or div-based dropdown) and pick the matching option."""
    el = find_one(driver, ref)
    if el is None:
        return False
    tag = (getattr(el, "tag_name", "") or "").lower()
    v = _coerce_value(value).strip()

    if tag == "select":
        with suppress(Exception):
            # Native <option> by visible text first, then by value.
            from selenium.webdriver.support.ui import Select  # type: ignore[import-not-found]

            sel = Select(el)
            with suppress(Exception):
                sel.select_by_visible_text(v)
                return True
            with suppress(Exception):
                sel.select_by_value(v)
                return True

    # Custom div-based dropdown: click to open, then click matching option.
    with suppress(Exception):
        el.click()
    by, css = parse_ref(ref)
    script = (
        "const root = document.querySelector(arguments[0]) || document.body;"
        " const target = arguments[1].toLowerCase();"
        " const opts = root.querySelectorAll('[role=\"option\"], li, .option, [data-value]');"
        " for (const o of opts) {"
        "   const t = (o.textContent||'').trim().toLowerCase();"
        "   if (t === target || t.startsWith(target)) { o.click(); return true; }"
        " }"
        " return false;"
    )
    try:
        return bool(driver.execute_script(script, css if by == "css selector" else "*", v))
    except Exception as e:
        log.debug("select_option JS fallback failed for %s: %s", ref, e)
        return False


def set_checkbox(driver: _DriverLike, ref: str, value: bool) -> bool:
    """Toggle a checkbox to ``value`` (only clicks when state differs)."""
    el = find_one(driver, ref)
    if el is None:
        return False
    try:
        current = bool(el.is_selected())
    except Exception:
        current = False
    if current != value:
        with suppress(Exception):
            el.click()
            return True
    return True


def click(driver: _DriverLike, ref: str) -> bool:
    el = find_one(driver, ref)
    if el is None:
        return False
    try:
        el.click()
        return True
    except Exception as e:
        log.debug("click failed for %s, trying JS: %s", ref, e)
        by, css = parse_ref(ref)
        if by == "css selector":
            with suppress(Exception):
                driver.execute_script("document.querySelector(arguments[0]).click();", css)
                return True
        return False


def upload(driver: _DriverLike, ref: str, path: str) -> bool:
    el = find_one(driver, ref)
    if el is None:
        return False
    with suppress(Exception):
        el.send_keys(path)
        return True
    return False


# ---------------------------------------------------------------------------
# Batched form fill
# ---------------------------------------------------------------------------


def fill_form(driver: _DriverLike, fields: dict[str, Any]) -> dict[str, bool]:
    """Fill every (ref → value) pair. Returns per-ref success map."""
    out: dict[str, bool] = {}
    for ref, value in fields.items():
        out[ref] = fill_input(driver, ref, value)
    return out


__all__ = [
    "click",
    "fill_form",
    "fill_input",
    "find_one",
    "parse_ref",
    "select_option",
    "set_checkbox",
    "upload",
]
