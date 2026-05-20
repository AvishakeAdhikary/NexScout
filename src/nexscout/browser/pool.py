"""Per-worker browser pool (§13.1).

Each worker gets:

* A cloned Chrome profile dir at ``~/.nexscout/chrome-workers/worker-<w>/``
  (caches and locks excluded).
* A patched ``Default/Preferences`` JSON (suppresses the "Restore pages?" nag).
* A unique CDP port (``9222 + worker_id``); zombies on that port are killed
  first.
* All §13.1 launch flags (headless, --remote-debugging-port=…, ...).
* On *nix, a new process group via ``os.setsid``.
* Stealth patches via :func:`browser.stealth.apply_stealth`.
* A wiped ``~/.nexscout/apply-workers/worker-<w>/`` per job.

Tests inject a :class:`BrowserFactory`-compatible callable to avoid launching
real Chrome. See :class:`BrowserPool` / :class:`PoolBrowserFactory`.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..core.config import apply_workers_dir, chrome_workers_dir, get_chrome_path
from ..core.errors import ConfigError
from .driver import WorkerBrowser
from .stealth import apply_stealth

log = logging.getLogger(__name__)


#: Files/folders excluded when cloning a Chrome profile (verbatim §13.1).
EXCLUDED_PROFILE_PATHS: tuple[str, ...] = (
    "ShaderCache",
    "GrShaderCache",
    "Service Worker",
    "Cache",
    "Code Cache",
    "GPUCache",
    "CacheStorage",
    "Crashpad",
    "BrowserMetrics",
    "SafeBrowsing",
    "Crowd Deny",
    "MEIPreload",
    "SSLErrorAssistant",
    "recovery",
    "Temp",
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
)


# ---------------------------------------------------------------------------
# Source profile detection
# ---------------------------------------------------------------------------


def chrome_user_data_dir() -> Path | None:
    """Locate the OS Chrome user data dir (cross-platform).

    Windows: ``%LOCALAPPDATA%\\Google\\Chrome\\User Data``.
    macOS  : ``~/Library/Application Support/Google/Chrome``.
    Linux  : ``~/.config/google-chrome``.
    """
    override = os.environ.get("CHROME_USER_DATA_DIR")
    if override:
        p = Path(override).expanduser()
        return p if p.exists() else None

    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            p = Path(local) / "Google" / "Chrome" / "User Data"
            if p.exists():
                return p
        return None
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        return p if p.exists() else None
    p = Path.home() / ".config" / "google-chrome"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Profile cloning + Preferences patching
# ---------------------------------------------------------------------------


def clone_profile(*, source: Path, dest: Path) -> None:
    """Clone ``source`` Chrome profile to ``dest`` skipping caches/locks.

    Idempotent: if ``dest`` already contains a Default/ subdir, the function
    leaves it alone.
    """
    if (dest / "Default").exists():
        log.debug("profile %s already cloned", dest)
        return
    dest.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        # Make a minimal skeleton if the OS Chrome profile is missing.
        (dest / "Default").mkdir(parents=True, exist_ok=True)
        return

    for item in source.iterdir():
        if item.name in EXCLUDED_PROFILE_PATHS:
            continue
        target = dest / item.name
        try:
            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    symlinks=False,
                    ignore=shutil.ignore_patterns(*EXCLUDED_PROFILE_PATHS),
                    dirs_exist_ok=True,
                )
            else:
                shutil.copy2(item, target)
        except (OSError, shutil.Error) as e:
            log.debug("skip clone of %s: %s", item, e)


def patch_preferences(profile_dir: Path) -> None:
    """Patch ``Default/Preferences`` to suppress restore prompts (§13.1)."""
    prefs_path = profile_dir / "Default" / "Preferences"
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if prefs_path.exists():
        try:
            data = json.loads(prefs_path.read_text(encoding="utf-8") or "{}")
        except (OSError, json.JSONDecodeError):
            data = {}

    profile = data.setdefault("profile", {})
    profile["exit_type"] = "Normal"

    session = data.setdefault("session", {})
    session["restore_on_startup"] = 4
    session.pop("startup_urls", None)

    credentials = data.setdefault("credentials_enable_service", False)
    _ = credentials  # not strictly necessary; set explicitly
    data["credentials_enable_service"] = False

    password_manager = data.setdefault("password_manager", {})
    password_manager["saving_enabled"] = False

    autofill = data.setdefault("autofill", {})
    autofill["profile_enabled"] = False

    prefs_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Zombie port reaping
# ---------------------------------------------------------------------------


def kill_zombies_on_port(port: int) -> None:
    """Best-effort kill of any process listening on ``port``.

    Windows: ``netstat -ano | findstr LISTENING`` + ``taskkill /F /T /PID``.
    *nix:    ``lsof -ti:<port>`` + ``kill -9 -<pgid>``.
    """
    if sys.platform == "win32":
        _kill_windows(port)
    else:
        _kill_posix(port)


def _kill_windows(port: int) -> None:  # pragma: no cover — OS-dependent
    try:
        proc = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        log.debug("netstat failed: %s", e)
        return
    pids: set[str] = set()
    for line in proc.stdout.splitlines():
        if "LISTENING" not in line or f":{port} " not in line.replace(" ", " "):
            # Lazy: just substring-match the port.
            if f":{port}" not in line:
                continue
            if "LISTENING" not in line:
                continue
        parts = line.split()
        if parts:
            pid = parts[-1]
            if pid.isdigit():
                pids.add(pid)
    for pid in pids:
        with suppress(subprocess.SubprocessError, FileNotFoundError, OSError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=False)


def _kill_posix(port: int) -> None:  # pragma: no cover — OS-dependent
    try:
        proc = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as e:
        log.debug("lsof failed: %s", e)
        return
    for pid in proc.stdout.splitlines():
        pid_s = pid.strip()
        if not pid_s.isdigit():
            continue
        with suppress(OSError, ProcessLookupError):
            os.killpg(int(pid_s), 9)
        with suppress(OSError, ProcessLookupError):
            os.kill(int(pid_s), 9)


# ---------------------------------------------------------------------------
# Pool / factory protocol
# ---------------------------------------------------------------------------


class PoolBrowserFactory(Protocol):
    """Test seam — pool delegates real driver creation here."""

    def launch(
        self,
        *,
        worker_id: int,
        cdp_port: int,
        profile_dir: Path,
        headless: bool,
        chrome_binary: str | None,
    ) -> Any: ...


@dataclass
class _PoolEntry:
    """Internal record per active worker browser."""

    worker_id: int
    browser: WorkerBrowser
    profile_dir: Path


class BrowserPool:
    """Acquire / release :class:`WorkerBrowser` instances by worker id."""

    def __init__(
        self,
        *,
        workers: int,
        headless: bool = True,
        factory: PoolBrowserFactory | None = None,
        base_port: int = 9222,
        chrome_root: Path | None = None,
        apply_root: Path | None = None,
        chrome_binary: str | None = None,
    ) -> None:
        self.workers = workers
        self.headless = headless
        self.factory = factory or _DefaultPoolFactory()
        self.base_port = base_port
        self.chrome_root = chrome_root or chrome_workers_dir()
        self.apply_root = apply_root or apply_workers_dir()
        self.chrome_binary = chrome_binary or get_chrome_path()
        self._active: dict[int, _PoolEntry] = {}

    # ------------------------------------------------------------------
    # Acquire / release
    # ------------------------------------------------------------------

    def acquire(self, worker_id: int) -> WorkerBrowser:
        """Return a launched browser for ``worker_id``. Idempotent."""
        existing = self._active.get(worker_id)
        if existing is not None:
            self._wipe_apply_workspace(worker_id)
            return existing.browser

        profile_dir = self._ensure_profile(worker_id)
        port = self.base_port + worker_id
        kill_zombies_on_port(port)
        self._wipe_apply_workspace(worker_id)

        try:
            raw_driver = self.factory.launch(
                worker_id=worker_id,
                cdp_port=port,
                profile_dir=profile_dir,
                headless=self.headless,
                chrome_binary=self.chrome_binary,
            )
        except Exception as e:
            raise ConfigError(f"failed to launch worker {worker_id}: {e}") from e

        with suppress(Exception):
            apply_stealth(raw_driver)

        browser = WorkerBrowser(
            worker_id=worker_id,
            cdp_port=port,
            driver=raw_driver,
            profile_dir=str(profile_dir),
        )
        self._active[worker_id] = _PoolEntry(worker_id=worker_id, browser=browser, profile_dir=profile_dir)
        return browser

    def release(self, worker_id: int, browser: WorkerBrowser | None = None) -> None:
        """Quit and forget the browser for ``worker_id``."""
        _ = browser  # signature mirror — pool tracks its own entry
        entry = self._active.pop(worker_id, None)
        if entry is None:
            return
        with suppress(Exception):
            entry.browser.quit()

    def close_all(self) -> None:
        """Quit every active browser."""
        for worker_id in list(self._active):
            self.release(worker_id)

    # ------------------------------------------------------------------
    # Filesystem helpers
    # ------------------------------------------------------------------

    def _ensure_profile(self, worker_id: int) -> Path:
        target = self.chrome_root / f"worker-{worker_id}"
        if not (target / "Default").exists():
            self._clone_seed(target, worker_id)
        patch_preferences(target)
        return target

    def _clone_seed(self, target: Path, worker_id: int) -> None:
        """Prefer cloning from worker-0 (warm cookies), else from the OS profile."""
        target.mkdir(parents=True, exist_ok=True)
        seed_candidates: list[Path] = []
        if worker_id != 0:
            seed_candidates.append(self.chrome_root / "worker-0")
        os_profile = chrome_user_data_dir()
        if os_profile is not None:
            seed_candidates.append(os_profile)
        for seed in seed_candidates:
            if seed.exists():
                clone_profile(source=seed, dest=target)
                return
        # No seed available — skeleton only.
        (target / "Default").mkdir(parents=True, exist_ok=True)

    def _wipe_apply_workspace(self, worker_id: int) -> None:
        path = self.apply_root / f"worker-{worker_id}"
        with suppress(OSError):
            if path.exists():
                shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Default factory — undetected_chromedriver under the hood
# ---------------------------------------------------------------------------


class _DefaultPoolFactory:
    """Real Chrome launcher. Always lazy-imports ``undetected_chromedriver``."""

    def launch(
        self,
        *,
        worker_id: int,
        cdp_port: int,
        profile_dir: Path,
        headless: bool,
        chrome_binary: str | None,
    ) -> Any:  # pragma: no cover — needs a real Chrome install
        try:
            import undetected_chromedriver as uc  # type: ignore[import-not-found]
        except ImportError as e:
            raise ConfigError("undetected_chromedriver is not installed") from e

        if not chrome_binary:
            raise ConfigError("Chrome/Chromium not found on PATH")

        opts = uc.ChromeOptions()
        flags = [
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1024,768",
            "--disable-session-crashed-bubble",
            "--disable-features=InfiniteSessionRestore,PasswordManagerOnboarding",
            "--hide-crash-restore-bubble",
            "--noerrdialogs",
            "--password-store=basic",
            "--disable-save-password-bubble",
            "--disable-popup-blocking",
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            "--deny-permission-prompts",
            "--disable-notifications",
        ]
        for f in flags:
            opts.add_argument(f)
        if headless:
            opts.add_argument("--headless=new")
        opts.binary_location = chrome_binary

        # New process group on *nix so we can kill the whole tree.
        preexec = os.setsid if sys.platform != "win32" else None
        return uc.Chrome(
            options=opts,
            service_args=[],
            service_creationflags=0,
            preexec_fn=preexec,  # type: ignore[arg-type]
        )

    def __init__(self) -> None:
        # Holder so dataclass shenanigans don't matter.
        self._worker_id = 0


__all__ = [
    "EXCLUDED_PROFILE_PATHS",
    "BrowserPool",
    "PoolBrowserFactory",
    "chrome_user_data_dir",
    "clone_profile",
    "kill_zombies_on_port",
    "patch_preferences",
]
