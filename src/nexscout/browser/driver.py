"""Undetected_chromedriver factory + worker wrapper.

This module exposes:

* :class:`BrowserFactory` — Protocol used by enrichment/apply tests to inject
  a mock browser without launching real Chrome.
* :class:`UndetectedFactory` — default factory backed by
  ``undetected_chromedriver``.
* :class:`WorkerBrowser` — wrapper returned by the pool to workers. It exposes
  ``driver``, ``cdp_port``, ``worker_id`` plus helpers for ``execute_cdp`` and
  page utilities.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.config import get_chrome_path
from ..core.errors import ConfigError
from .stealth import apply_stealth

log = logging.getLogger(__name__)


class BrowserFactory(Protocol):
    """Protocol so tests can inject mock browsers into enrichment."""

    def make(self, *, headless: bool = True) -> Any: ...


class UndetectedFactory:
    """Default :class:`BrowserFactory` backed by ``undetected_chromedriver``."""

    def __init__(self, *, window_size: tuple[int, int] = (1024, 768), page_load_timeout: int = 30) -> None:
        self.window_size = window_size
        self.page_load_timeout = page_load_timeout

    def make(self, *, headless: bool = True) -> Any:
        try:
            import undetected_chromedriver as uc  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover — env-dependent
            raise ConfigError("undetected_chromedriver is not installed") from e

        chrome_path = get_chrome_path()
        if not chrome_path:
            raise ConfigError("Chrome/Chromium not found on PATH")

        opts = uc.ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument(f"--window-size={self.window_size[0]},{self.window_size[1]}")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--disable-notifications")
        opts.binary_location = chrome_path

        driver = uc.Chrome(options=opts)
        with suppress(Exception):
            driver.set_page_load_timeout(self.page_load_timeout)
        apply_stealth(driver)
        return driver


# ---------------------------------------------------------------------------
# WorkerBrowser — richer wrapper used by the apply pool
# ---------------------------------------------------------------------------


@dataclass
class WorkerBrowser:
    """Wrapper around a Selenium-like driver returned to apply workers.

    The pool sets ``driver``, ``cdp_port`` and ``worker_id``; everything else
    is helper methods routed through the underlying driver.
    """

    worker_id: int
    cdp_port: int
    driver: Any
    profile_dir: str | None = None

    # ------------------------------------------------------------------
    # Page tools
    # ------------------------------------------------------------------

    def navigate(self, url: str) -> None:
        self.driver.get(url)

    def screenshot(self, path: str) -> bool:
        try:
            return bool(self.driver.save_screenshot(path))
        except Exception as e:
            log.debug("screenshot failed: %s", e)
            return False

    @property
    def page_source(self) -> str:
        try:
            return str(self.driver.page_source or "")
        except Exception:
            return ""

    @property
    def current_url(self) -> str:
        return str(getattr(self.driver, "current_url", "") or "")

    @property
    def title(self) -> str:
        return str(getattr(self.driver, "title", "") or "")

    # ------------------------------------------------------------------
    # CDP / JS
    # ------------------------------------------------------------------

    def execute_script(self, script: str, *args: Any) -> Any:
        return self.driver.execute_script(script, *args)

    def execute_cdp(self, cmd: str, params: dict[str, Any] | None = None) -> Any:
        """Run a CDP command (e.g. ``Page.addScriptToEvaluateOnNewDocument``)."""
        params = params or {}
        try:
            return self.driver.execute_cdp_cmd(cmd, params)
        except AttributeError as e:
            raise ConfigError("driver does not expose execute_cdp_cmd") from e

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def quit(self) -> None:
        with suppress(Exception):
            self.driver.quit()

    def __getattr__(self, name: str) -> Any:
        """Delegate any unwrapped attribute to the underlying Selenium driver.

        The apply tools (``navigate``/``click``/``fill_form``/``switch_tab``/...)
        call raw driver members directly on the browser handed to them —
        ``get``, ``find_element(s)``, ``window_handles``, ``switch_to``,
        ``save_screenshot``, ``current_window_handle``, etc. Rather than
        re-declare each, proxy unknown attributes to ``self.driver`` so the
        wrapper behaves like the driver it wraps. Guarded against recursion
        before ``driver`` is set (dataclass ``__init__``) and against dunder
        probes (copy/pickle/etc.).
        """
        if name.startswith("__") or name == "driver":
            raise AttributeError(name)
        driver = self.__dict__.get("driver")
        if driver is None:
            raise AttributeError(name)
        return getattr(driver, name)


__all__ = [
    "BrowserFactory",
    "UndetectedFactory",
    "WorkerBrowser",
]
