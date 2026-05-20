"""Per-application bundle directory helpers (§16).

Layout::

    ~/.nexscout/applications/<06d-job_id>/
    ├── resume.tex / resume.pdf / resume.txt
    ├── cover_letter.tex / cover_letter.pdf / cover_letter.txt
    ├── job.json / transcript.jsonl / result.json
    ├── screenshots/
    └── _REPORT.json
"""

from __future__ import annotations

from pathlib import Path

from .config import applications_dir


def bundle_dir_for(job_id: int, *, root: Path | None = None) -> Path:
    """Return the bundle directory for ``job_id`` (always 6-digit zero-padded)."""
    base = root if root is not None else applications_dir()
    bundle = base / f"{int(job_id):06d}"
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "screenshots").mkdir(parents=True, exist_ok=True)
    return bundle


def write_bundle_file(job_id: int, filename: str, data: str | bytes, *, root: Path | None = None) -> Path:
    """Write a file inside the job's bundle directory and return the path."""
    target = bundle_dir_for(job_id, root=root) / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        target.write_text(data, encoding="utf-8")
    else:
        target.write_bytes(data)
    return target


def read_bundle_file(job_id: int, filename: str, *, root: Path | None = None) -> str:
    """Read a UTF-8 file from the job's bundle directory."""
    return (bundle_dir_for(job_id, root=root) / filename).read_text(encoding="utf-8")
