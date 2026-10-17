"""Back up NexScout: a Postgres custom-format dump plus the object store, with a manifest.

    cd backend && uv run python ../scripts/backup.py [--out ../backups]

Uses `pg_dump` inside the compose `postgres` container (no local Postgres tools needed).
The manifest records row counts per table and a SHA-256 for every stored file, so a restore
can be verified (scripts/restore.py). Backups contain personal data: store them encrypted and
access-controlled (docs/OPERATIONS.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from nexscout.config import get_settings

ROOT = Path(__file__).resolve().parents[1]


def compose(*args: str, stdout: object = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, check=True, stdout=stdout  # type: ignore[arg-type]
    )


def table_counts(url: str) -> dict[str, int]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            tables = [
                r[0]
                for r in conn.execute(text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1"))
            ]
            return {
                t: int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0)  # noqa: S608
                for t in tables
            }
    finally:
        engine.dispose()


def file_hashes(storage: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if storage.exists():
        for f in sorted(p for p in storage.rglob("*") if p.is_file()):
            out[f.relative_to(storage).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "backups")
    parser.add_argument("--db", default="nexscout")
    args = parser.parse_args()
    settings = get_settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = args.out / stamp
    target.mkdir(parents=True, exist_ok=False)

    url = settings.migration_database_url.get_secret_value()
    counts_before = table_counts(url)
    with (target / "db.dump").open("wb") as fh:
        compose("exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-Fc", args.db, stdout=fh)
    storage = Path(settings.storage_dir)
    with tarfile.open(target / "storage.tar.gz", "w:gz") as tar:
        if storage.exists():
            tar.add(storage, arcname="storage")
    manifest = {
        "created_at": stamp,
        "database": args.db,
        "row_counts": counts_before,
        "files": file_hashes(storage),
        "dump_bytes": (target / "db.dump").stat().st_size,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(target), "tables": len(counts_before),
                      "rows": sum(counts_before.values()), "files": len(manifest["files"]),
                      "dump_bytes": manifest["dump_bytes"]}))


if __name__ == "__main__":
    main()
