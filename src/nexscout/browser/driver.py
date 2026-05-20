"""Minimal undetected_chromedriver factory used by enrichment.

The full per-worker pool with profile cloning lands in M7. This module only
provides the cross-platform Chrome detection plus a single-driver builder.
``undetected_chromedriver`` is imported lazily so the rest of the codebase
can be loaded (and tested) without it installed.
"""

from __future__ import annotations

import logging
from contextlib import suppress
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
