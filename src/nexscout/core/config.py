"""Filesystem paths and cross-platform helpers."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def nexscout_dir() -> Path:
    """Return the root NexScout state directory.

    Honours the ``NEXSCOUT_DIR`` env var; defaults to ``~/.nexscout``.
    """
    override = os.environ.get("NEXSCOUT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".nexscout"


def profile_path() -> Path:
    return nexscout_dir() / "profile.yaml"


def database_path() -> Path:
    return nexscout_dir() / "nexscout.sqlite"


def budget_db_path() -> Path:
    return nexscout_dir() / "budget.sqlite"


def employers_path() -> Path:
    return nexscout_dir() / "employers.yaml"


def sites_path() -> Path:
    return nexscout_dir() / "sites.yaml"


def applications_dir() -> Path:
    return nexscout_dir() / "applications"


def chrome_workers_dir() -> Path:
    return nexscout_dir() / "chrome-workers"


def apply_workers_dir() -> Path:
    return nexscout_dir() / "apply-workers"


def ensure_dirs() -> None:
    """Create the directory tree if missing. Idempotent."""
    root = nexscout_dir()
    for sub in (root, applications_dir(), chrome_workers_dir(), apply_workers_dir()):
        sub.mkdir(parents=True, exist_ok=True)


def get_chrome_path() -> str | None:
    """Locate a Chrome / Chromium binary across Windows, macOS, Linux."""
    override = os.environ.get("CHROME_PATH")
    if override and Path(override).exists():
        return override

    candidates: list[str] = []
    if sys.platform == "win32":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            rf"{program_files}\Google\Chrome\Application\chrome.exe",
            rf"{program_files_x86}\Google\Chrome\Application\chrome.exe",
            rf"{local_app_data}\Google\Chrome\Application\chrome.exe",
            rf"{program_files}\Chromium\Application\chrome.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    else:
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

    for c in candidates:
        if Path(c).exists():
            return c

    for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
        which = shutil.which(name)
        if which:
            return which
    return None
