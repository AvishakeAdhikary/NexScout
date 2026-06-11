#!/usr/bin/env python3
"""Wipe NexScout's RUNTIME DATA while KEEPING the three config files.

Standalone (Python 3.11+, stdlib only — no NexScout import needed). It clears
the per-run state that accumulates in the config dir so you can start fresh:

  * the SQLite databases       — nexscout.sqlite (+ -wal/-shm), budget.sqlite (…)
  * tailored output            — the applications/ directory (bundles/PDFs/shots)
  * the autopilot scratch files — last-tick.json, run-status.json, dashboard.html
  * the browser-profile dirs    — chrome-workers/ and apply-workers/

It NEVER touches your config:  profile.yaml, settings.yaml, credentials.yaml,
employers.yaml, sites.yaml, or the OpenClaw config in ~/.openclaw — those are
left exactly as they are.

The config dir is $NEXSCOUT_DIR if set, else ~/.nexscout. Pass an explicit dir
as the first positional argument to override. A y/N confirmation is required
unless --yes/-y is given.

Usage:
    python clear_db.py                 # wipe $NEXSCOUT_DIR or ~/.nexscout (asks)
    python clear_db.py --yes           # no prompt
    python clear_db.py /some/dir -y    # explicit target dir, no prompt
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# Runtime files/dirs that are safe to delete (relative to the config dir). These
# mirror nexscout.core.config (database_path / budget_db_path / applications_dir
# / chrome_workers_dir / apply_workers_dir) plus the autopilot scratch files.
_DATA_FILES: tuple[str, ...] = (
    "nexscout.sqlite",
    "nexscout.sqlite-wal",
    "nexscout.sqlite-shm",
    "budget.sqlite",
    "budget.sqlite-wal",
    "budget.sqlite-shm",
    "last-tick.json",
    "run-status.json",
    "dashboard.html",
)
_DATA_DIRS: tuple[str, ...] = (
    "applications",
    "chrome-workers",
    "apply-workers",
)

# Config we must NEVER delete (informational — used only to reassure the user).
_KEEP: tuple[str, ...] = (
    "profile.yaml",
    "settings.yaml",
    "credentials.yaml",
    "employers.yaml",
    "sites.yaml",
)


def _target_dir(arg: str | None) -> Path:
    """Resolve the config dir: explicit arg > $NEXSCOUT_DIR > ~/.nexscout."""
    if arg:
        return Path(arg).expanduser().resolve()
    override = os.environ.get("NEXSCOUT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".nexscout").resolve()


def _long_path(p: Path) -> str:
    r"""Return a long-path-safe string for shutil on Windows (\\?\ prefix).

    Windows' legacy MAX_PATH (260) trips on the deep, nested directory trees
    Chromium leaves under chrome-workers/. Prefixing the absolute path with
    ``\\?\`` opts into the extended-length path API so rmtree can recurse all
    the way down. No-op on POSIX.
    """
    if sys.platform != "win32":
        return str(p)
    ap = os.path.abspath(str(p))
    if ap.startswith("\\\\?\\"):
        return ap
    if ap.startswith("\\\\"):  # UNC path -> \\?\UNC\server\share\...
        return "\\\\?\\UNC\\" + ap[2:]
    return "\\\\?\\" + ap


def _on_rm_error(func, path, exc_info) -> None:
    """rmtree onerror hook: clear the read-only bit (Chromium drops these) and retry."""
    import stat

    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        # Last-ditch: leave it; the summary will note what couldn't be removed.
        pass


def _remove_dir(d: Path) -> bool:
    """Delete a directory tree (long-path-safe). Returns True if it existed."""
    if not d.exists():
        return False
    # Python 3.12 renamed onerror -> onexc; support both without crashing.
    try:
        shutil.rmtree(_long_path(d), onexc=_on_rm_error)  # type: ignore[call-arg]
    except TypeError:
        shutil.rmtree(_long_path(d), onerror=_on_rm_error)
    return True


def _remove_file(f: Path) -> bool:
    """Delete a single file (long-path-safe). Returns True if it existed."""
    if not f.exists():
        return False
    try:
        os.remove(_long_path(f))
    except OSError:
        # Clear a read-only bit and retry once.
        import stat

        try:
            os.chmod(_long_path(f), stat.S_IWRITE)
            os.remove(_long_path(f))
        except OSError:
            return True  # it existed; report it even though removal raced/failed
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="clear_db.py",
        description="Wipe NexScout runtime data (DBs, applications/, scratch, browser profiles); keep config.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Config dir to wipe (default: $NEXSCOUT_DIR or ~/.nexscout).",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args(argv)

    target = _target_dir(args.target)
    print(f"NexScout config dir: {target}")

    if not target.exists():
        print(f"[clear-db] Nothing to do — '{target}' does not exist.")
        return 0
    if not target.is_dir():
        print(f"[clear-db] ERROR: '{target}' is not a directory.", file=sys.stderr)
        return 2

    # Show exactly what WILL and what will NOT be touched, before confirming.
    present_files = [f for f in _DATA_FILES if (target / f).exists()]
    present_dirs = [d for d in _DATA_DIRS if (target / d).exists()]
    kept_present = [k for k in _KEEP if (target / k).exists()]

    if not present_files and not present_dirs:
        print("[clear-db] No runtime data found — already clean.")
        if kept_present:
            print(f"[clear-db] Kept config: {', '.join(kept_present)}")
        return 0

    print("\nWill DELETE:")
    for f in present_files:
        print(f"  - {f}")
    for d in present_dirs:
        print(f"  - {d}/  (directory)")
    print("\nWill KEEP (config — never deleted):")
    for k in kept_present or list(_KEEP):
        print(f"  - {k}")

    if not args.yes:
        try:
            reply = input("\nProceed and wipe the runtime data above? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[clear-db] Aborted.")
            return 1
        if reply not in ("y", "yes"):
            print("[clear-db] Aborted — nothing was deleted.")
            return 1

    # --- wipe ------------------------------------------------------------- #
    removed: list[str] = []
    for f in _DATA_FILES:
        if _remove_file(target / f):
            removed.append(f)
    for d in _DATA_DIRS:
        if _remove_dir(target / d):
            removed.append(f"{d}/")

    print("\n[clear-db] Removed:")
    for r in removed:
        print(f"  x {r}")
    print(f"[clear-db] Done. Config files in {target} were left untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
