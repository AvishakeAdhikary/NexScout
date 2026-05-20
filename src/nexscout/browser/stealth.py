"""Stealth patches applied to every driver instance (§13.1).

The four patches:

* ``navigator.webdriver`` returns ``undefined``.
* ``cdc_*`` keys (left behind by ChromeDriver) are removed from ``window``.
* ``navigator.plugins`` returns a non-empty array (the default empty one is a
  bot tell).
* ``navigator.languages`` returns ``['en-US', 'en']``.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Protocol


class _DriverLike(Protocol):
    def execute_script(self, script: str, *args: Any) -> Any: ...

    def execute_cdp_cmd(self, cmd: str, params: dict[str, Any]) -> Any: ...


# Verbatim JS payload from §13.1 — applied to every page and via CDP so it
# also fires before page-scripts run.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
(() => {
  for (const k of Object.keys(window)) {
    if (k.indexOf('cdc_') === 0) {
      try { delete window[k]; } catch (e) {}
    }
  }
})();
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
""".strip()


def apply_stealth(driver: _DriverLike) -> None:
    """Apply the stealth JS to a driver.

    Uses ``Page.addScriptToEvaluateOnNewDocument`` (CDP) when available so the
    patches fire before the page's own scripts; otherwise falls back to a
    plain ``execute_script`` on the current document.
    """
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STEALTH_JS})
    except Exception:
        with suppress(Exception):
            driver.execute_script(STEALTH_JS)
