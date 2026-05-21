"""Tests for ``browser.pool`` / ``browser.driver`` / ``browser.stealth``.

We stub :class:`PoolBrowserFactory` to avoid launching real Chrome and mock
``subprocess.run`` / ``shutil.copytree`` for the zombie-kill and profile-clone
branches.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from nexscout.browser import driver as drv_mod
from nexscout.browser import pool as pool_mod
from nexscout.browser.driver import (
    UndetectedFactory,
    WorkerBrowser,
)
from nexscout.browser.pool import (
    EXCLUDED_PROFILE_PATHS,
    BrowserPool,
    chrome_user_data_dir,
    clone_profile,
    kill_zombies_on_port,
    patch_preferences,
)
from nexscout.browser.stealth import STEALTH_JS, apply_stealth
from nexscout.core.errors import ConfigError

# ---------------------------------------------------------------------------
# chrome_user_data_dir
# ---------------------------------------------------------------------------


def test_chrome_user_data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHROME_USER_DATA_DIR", str(tmp_path))
    assert chrome_user_data_dir() == tmp_path


def test_chrome_user_data_dir_override_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHROME_USER_DATA_DIR", "/path/nope/nope")
    assert chrome_user_data_dir() is None


def test_chrome_user_data_dir_platform_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive each platform branch — function returns None when target missing."""
    monkeypatch.delenv("CHROME_USER_DATA_DIR", raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("LOCALAPPDATA", "/no/such/path")
        assert chrome_user_data_dir() is None
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        assert chrome_user_data_dir() is None


# ---------------------------------------------------------------------------
# clone_profile / patch_preferences
# ---------------------------------------------------------------------------


def test_clone_profile_skips_already_cloned(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    (dest / "Default").mkdir(parents=True)
    # No-op when Default exists.
    clone_profile(source=src, dest=dest)
    assert (dest / "Default").exists()


def test_clone_profile_skeleton_when_source_missing(tmp_path: Path) -> None:
    src = tmp_path / "missing"
    dest = tmp_path / "dest"
    clone_profile(source=src, dest=dest)
    assert (dest / "Default").exists()


def test_clone_profile_copies_files_and_skips_excluded(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "Default").mkdir()
    (src / "Default" / "Preferences").write_text("{}")
    (src / "Cache").mkdir()
    (src / "Cache" / "junk").write_text("noise")
    (src / "Cookies").write_text("yum")

    dest = tmp_path / "dest"
    clone_profile(source=src, dest=dest)
    assert (dest / "Default" / "Preferences").exists()
    assert (dest / "Cookies").exists()
    assert not (dest / "Cache").exists()


def test_clone_profile_handles_copy_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").mkdir()
    (src / "b.txt").write_text("hello")
    dest = tmp_path / "dest"

    import shutil

    def _bad_copytree(*a: Any, **kw: Any) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(shutil, "copytree", _bad_copytree)
    clone_profile(source=src, dest=dest)  # should not raise


def test_excluded_profile_paths_includes_expected_caches() -> None:
    for item in ("Cache", "GPUCache", "SingletonLock"):
        assert item in EXCLUDED_PROFILE_PATHS


def test_patch_preferences_creates_and_patches(tmp_path: Path) -> None:
    patch_preferences(tmp_path)
    data = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert data["session"]["restore_on_startup"] == 4
    assert data["profile"]["exit_type"] == "Normal"
    assert data["password_manager"]["saving_enabled"] is False


def test_patch_preferences_merges_existing(tmp_path: Path) -> None:
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text(json.dumps({"profile": {"name": "x"}, "extra": 1}))
    patch_preferences(tmp_path)
    data = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert data["profile"]["name"] == "x"
    assert data["extra"] == 1
    assert data["profile"]["exit_type"] == "Normal"


def test_patch_preferences_handles_corrupt_prefs(tmp_path: Path) -> None:
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Preferences").write_text("{not valid")
    patch_preferences(tmp_path)
    data = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert "profile" in data


# ---------------------------------------------------------------------------
# kill_zombies_on_port — both platform branches
# ---------------------------------------------------------------------------


def test_kill_zombies_dispatches_on_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, int] = {"win": 0, "posix": 0}
    monkeypatch.setattr(pool_mod, "_kill_windows", lambda port: called.__setitem__("win", called["win"] + 1))
    monkeypatch.setattr(pool_mod, "_kill_posix", lambda port: called.__setitem__("posix", called["posix"] + 1))
    kill_zombies_on_port(9222)
    assert (called["win"] + called["posix"]) == 1


# ---------------------------------------------------------------------------
# BrowserPool — with a fake factory
# ---------------------------------------------------------------------------


class _FakeFactory:
    """Records launch parameters and returns a MagicMock driver."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def launch(self, **kw: Any) -> Any:
        self.calls.append(kw)
        d = MagicMock()
        d.execute_cdp_cmd = MagicMock()
        return d


@pytest.fixture
def pool_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    chrome_root = tmp_path / "chrome"
    apply_root = tmp_path / "apply"
    chrome_root.mkdir()
    apply_root.mkdir()
    # Stop kill_zombies_on_port from actually trying anything.
    monkeypatch.setattr(pool_mod, "kill_zombies_on_port", lambda port: None)
    monkeypatch.setattr(pool_mod, "chrome_user_data_dir", lambda: None)
    return chrome_root, apply_root


def test_pool_acquire_creates_profile_dir(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    fac = _FakeFactory()
    pool = BrowserPool(
        workers=1,
        factory=fac,
        chrome_root=chrome_root,
        apply_root=apply_root,
        chrome_binary="/path/to/chrome",
    )
    browser = pool.acquire(0)
    assert isinstance(browser, WorkerBrowser)
    assert fac.calls
    # Profile dir was cloned/created.
    assert (chrome_root / "worker-0" / "Default").exists()
    # Apply workspace wiped+recreated.
    assert (apply_root / "worker-0").exists()


def test_pool_acquire_returns_existing(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    fac = _FakeFactory()
    pool = BrowserPool(workers=1, factory=fac, chrome_root=chrome_root, apply_root=apply_root)
    b1 = pool.acquire(0)
    b2 = pool.acquire(0)
    assert b1 is b2
    assert len(fac.calls) == 1


def test_pool_acquire_failure_raises(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths

    class _Bad:
        def launch(self, **kw: Any) -> Any:
            raise RuntimeError("driver crash")

    pool = BrowserPool(workers=1, factory=_Bad(), chrome_root=chrome_root, apply_root=apply_root)
    with pytest.raises(ConfigError):
        pool.acquire(0)


def test_pool_release(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    fac = _FakeFactory()
    pool = BrowserPool(workers=1, factory=fac, chrome_root=chrome_root, apply_root=apply_root)
    pool.acquire(0)
    pool.release(0)
    # second release is a no-op (no entry left).
    pool.release(0)


def test_pool_close_all(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    fac = _FakeFactory()
    pool = BrowserPool(workers=2, factory=fac, chrome_root=chrome_root, apply_root=apply_root)
    pool.acquire(0)
    pool.acquire(1)
    pool.close_all()
    assert pool._active == {}


def test_pool_acquire_wipes_apply_workspace_each_call(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    fac = _FakeFactory()
    pool = BrowserPool(workers=1, factory=fac, chrome_root=chrome_root, apply_root=apply_root)
    pool.acquire(0)
    # Drop a file in the workspace and acquire again — the cached browser is
    # returned and the workspace is wiped.
    (apply_root / "worker-0" / "stale.txt").write_text("x")
    pool.acquire(0)
    assert not (apply_root / "worker-0" / "stale.txt").exists()


def test_pool_uses_worker_0_seed_if_present(pool_paths: tuple[Path, Path]) -> None:
    chrome_root, apply_root = pool_paths
    # Pre-seed worker-0 with a Default dir + a cookie file.
    (chrome_root / "worker-0").mkdir()
    (chrome_root / "worker-0" / "Default").mkdir()
    (chrome_root / "worker-0" / "Cookies").write_text("x")
    fac = _FakeFactory()
    pool = BrowserPool(workers=2, factory=fac, chrome_root=chrome_root, apply_root=apply_root)
    pool.acquire(1)
    # worker-1 got seeded from worker-0.
    assert (chrome_root / "worker-1" / "Cookies").exists()


# ---------------------------------------------------------------------------
# UndetectedFactory
# ---------------------------------------------------------------------------


def test_undetected_factory_chrome_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv_mod, "get_chrome_path", lambda: None)
    f = UndetectedFactory()
    with pytest.raises(ConfigError):
        f.make()


def test_undetected_factory_creates_via_uc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv_mod, "get_chrome_path", lambda: "/path/to/chrome")
    fake_chrome = MagicMock()
    fake_options = MagicMock()
    fake_uc = SimpleNamespace(
        ChromeOptions=lambda: fake_options,
        Chrome=lambda options: fake_chrome,
    )
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", fake_uc)
    f = UndetectedFactory()
    d = f.make(headless=True)
    assert d is fake_chrome
    # Stealth was applied.
    fake_chrome.execute_cdp_cmd.assert_called()


# ---------------------------------------------------------------------------
# WorkerBrowser
# ---------------------------------------------------------------------------


def test_worker_browser_helpers() -> None:
    fake = MagicMock()
    fake.page_source = "<html/>"
    fake.current_url = "https://x.com"
    fake.title = "X"
    fake.save_screenshot.return_value = True
    wb = WorkerBrowser(worker_id=0, cdp_port=9222, driver=fake)
    wb.navigate("https://y.com")
    fake.get.assert_called_once_with("https://y.com")
    assert wb.screenshot("/tmp/x.png")
    assert wb.page_source == "<html/>"
    assert wb.current_url == "https://x.com"
    assert wb.title == "X"
    wb.execute_script("doit")
    fake.execute_script.assert_called()
    wb.execute_cdp("Page.x", {})
    wb.quit()


def test_worker_browser_screenshot_failure() -> None:
    fake = MagicMock()
    fake.save_screenshot.side_effect = RuntimeError("disk")
    wb = WorkerBrowser(worker_id=0, cdp_port=9222, driver=fake)
    assert wb.screenshot("/tmp/x.png") is False


def test_worker_browser_page_source_failure() -> None:
    class _Bad:
        @property
        def page_source(self) -> str:
            raise RuntimeError("dead")

    wb = WorkerBrowser(worker_id=0, cdp_port=9222, driver=_Bad())
    assert wb.page_source == ""


def test_worker_browser_execute_cdp_attribute_error() -> None:
    drv = SimpleNamespace()  # no execute_cdp_cmd
    wb = WorkerBrowser(worker_id=0, cdp_port=9222, driver=drv)
    with pytest.raises(ConfigError):
        wb.execute_cdp("Page.x")


def test_worker_browser_quit_swallows_exceptions() -> None:
    fake = MagicMock()
    fake.quit.side_effect = RuntimeError("nope")
    WorkerBrowser(worker_id=0, cdp_port=9222, driver=fake).quit()


# ---------------------------------------------------------------------------
# stealth.apply_stealth
# ---------------------------------------------------------------------------


def test_apply_stealth_uses_cdp_first() -> None:
    fake = MagicMock()
    apply_stealth(fake)
    fake.execute_cdp_cmd.assert_called_once_with(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": STEALTH_JS},
    )


def test_apply_stealth_falls_back_to_execute_script() -> None:
    fake = MagicMock()
    fake.execute_cdp_cmd.side_effect = RuntimeError("no CDP")
    apply_stealth(fake)
    fake.execute_script.assert_called()


def test_apply_stealth_swallows_all_failures() -> None:
    fake = MagicMock()
    fake.execute_cdp_cmd.side_effect = RuntimeError("nope")
    fake.execute_script.side_effect = RuntimeError("also nope")
    apply_stealth(fake)  # should not raise
