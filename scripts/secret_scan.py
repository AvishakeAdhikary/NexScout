"""Scan tracked files (and, with --history, every commit) for likely secrets.

    uv run --project backend python scripts/secret_scan.py [--history]

Exits 1 on findings. Obvious test placeholders (sk-test-..., example.com passwords in tests)
are allowed explicitly below so real keys stand out.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "aws access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "anthropic key": re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "openai key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack token": re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    "nexscout access token": re.compile(r"\bnxs_[A-Za-z0-9_-]{40,}\b"),
    "connection string with password": re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^:\s/]+:(?!nexscout_\w+_dev@|postgres_dev_only@)[^@\s]{6,}@"
    ),
}
ALLOWED = (
    "sk-test-", "sk-probe-", "nxs_wrong", 'nxs_" + "x"', "nxs_...",
)
SKIP_SUFFIXES = (".png", ".ico", ".pdf", ".docx", ".lock", ".zip", ".woff2")


def scan_text(path: str, text: str) -> list[str]:
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if any(a in line for a in ALLOWED):
            continue
        for name, pat in PATTERNS.items():
            if pat.search(line):
                hits.append(f"{path}:{lineno}: {name}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    hits: list[str] = []
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    for f in files:
        if f.endswith(SKIP_SUFFIXES) or "package-lock.json" in f or f.endswith("openapi.json"):
            continue
        try:
            hits += scan_text(f, (ROOT / f).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    if args.history:
        log = subprocess.run(["git", "log", "-p", "--all", "--no-color"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             check=True).stdout
        hits += [f"history {h}" for h in scan_text("git-log", log)]
    print(f"scanned {len(files)} tracked files{' + full history' if args.history else ''}: "
          f"{len(hits)} finding(s)")
    for h in hits:
        print("  " + h)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
