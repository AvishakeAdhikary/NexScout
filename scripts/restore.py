"""Restore a NexScout backup and verify it against its manifest.

    cd backend && uv run python ../scripts/restore.py BACKUP_DIR --db nexscout_restore_check \
        --storage-dir ../data/restore_check [--drop-after]

Restores into a *separate* database by default (refuses to overwrite the live `nexscout`
database unless --i-know-this-replaces-live-data is given), extracts the object store, and
verifies every table's row count and every file's SHA-256 against the backup manifest.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from backup import ROOT, compose, file_hashes, table_counts

from nexscout.config import get_settings


def psql(sql: str) -> None:
    compose("exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U", "postgres",
            "-d", "postgres", "-c", sql)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    parser.add_argument("--db", default="nexscout_restore_check")
    parser.add_argument("--storage-dir", type=Path, default=ROOT / "data" / "restore_check")
    parser.add_argument("--drop-after", action="store_true")
    parser.add_argument("--i-know-this-replaces-live-data", action="store_true")
    args = parser.parse_args()
    if args.db == "nexscout" and not args.i_know_this_replaces_live_data:
        print("Refusing to restore over the live database. Choose another --db.", file=sys.stderr)
        return 2
    manifest = json.loads((args.backup / "manifest.json").read_text(encoding="utf-8"))

    psql(f'DROP DATABASE IF EXISTS "{args.db}" WITH (FORCE)')
    psql(f'CREATE DATABASE "{args.db}" OWNER nexscout_owner')
    with (args.backup / "db.dump").open("rb") as fh:
        subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres", "pg_restore", "-U", "postgres",
             "-d", args.db, "--exit-on-error"],
            cwd=ROOT, check=True, stdin=fh,
        )
    if args.storage_dir.exists():
        shutil.rmtree(args.storage_dir)
    args.storage_dir.mkdir(parents=True)
    with tarfile.open(args.backup / "storage.tar.gz", "r:gz") as tar:
        tar.extractall(args.storage_dir, filter="data")  # rejects absolute/.. paths and links
    restored_storage = args.storage_dir / "storage"

    base = get_settings().migration_database_url.get_secret_value().rsplit("/", 1)[0]
    counts = table_counts(f"{base}/{args.db}")
    files = file_hashes(restored_storage)
    count_diff = {t: (n, counts.get(t)) for t, n in manifest["row_counts"].items()
                  if counts.get(t) != n}
    missing = [f for f in manifest["files"] if f not in files]
    changed = [f for f, h in manifest["files"].items() if f in files and files[f] != h]
    ok = not count_diff and not missing and not changed
    print(json.dumps({"restored_db": args.db, "tables": len(counts), "rows": sum(counts.values()),
                      "files": len(files), "row_count_mismatches": count_diff,
                      "missing_files": len(missing), "changed_files": len(changed), "ok": ok}))
    if args.drop_after:
        psql(f'DROP DATABASE IF EXISTS "{args.db}" WITH (FORCE)')
        shutil.rmtree(args.storage_dir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
