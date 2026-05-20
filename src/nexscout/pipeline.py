"""Pipeline orchestrator (§7 of plan.md).

Minimal sequential ``run(stages, profile, db)`` wiring the six stages together.
Streaming mode (per-stage worker threads polling the DB) is deferred to M11 —
sequential is sufficient for M5's end-to-end demonstration.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .core.bundle import bundle_dir_for, write_bundle_file
from .core.profile import Profile
from .llm.router import LLMRouter
from .scoring.cover_letter import write_cover_letter
from .scoring.render.engine import LatexEngineError, render_cover_letter_pdf, render_resume_pdf
from .scoring.scorer import persist_score, score_job
from .scoring.tailor import tailor_resume
from .scoring.validator import Mode

log = logging.getLogger(__name__)

STAGE_NAMES: tuple[str, ...] = ("discover", "enrich", "score", "tailor", "cover", "render")


def _ts() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Per-row stages
# ---------------------------------------------------------------------------


def run_score_stage(*, conn: sqlite3.Connection, router: LLMRouter, profile: Profile, limit: int = 0) -> int:
    """Score every row with ``full_description IS NOT NULL AND fit_score IS NULL``."""
    sql = (
        "SELECT rowid AS id, url, title, site, location, full_description "
        "FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    n = 0
    for row in conn.execute(sql).fetchall():
        job = dict(row)
        score, reasoning = score_job(router, profile, job)
        persist_score(conn, job["url"], score, reasoning)
        n += 1
    return n


def run_tailor_stage(
    *,
    conn: sqlite3.Connection,
    router: LLMRouter,
    profile: Profile,
    mode: Mode = "normal",
    limit: int = 0,
) -> int:
    """Tailor every eligible row; persist text + path; bump attempts."""
    sql = (
        "SELECT rowid AS id, url, title, site, location, full_description, fit_score "
        "FROM jobs "
        "WHERE fit_score >= ? "
        "  AND tailored_resume_path IS NULL "
        "  AND COALESCE(tailor_attempts, 0) < 5"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    n = 0
    for row in conn.execute(sql, (profile.search.min_score,)).fetchall():
        job = dict(row)
        result = tailor_resume(router=router, profile=profile, job=job, mode=mode)
        if result.status == "approved" and result.text:
            txt_path = write_bundle_file(int(job["id"]), "resume.txt", result.text)
            write_bundle_file(int(job["id"]), "_REPORT.json", json.dumps({
                "attempts": result.attempts,
                "judge_verdict": result.judge_verdict,
                "judge_issues": result.judge_issues,
            }, indent=2))
            conn.execute(
                "UPDATE jobs SET tailored_resume_path=?, tailored_at=?, "
                "tailor_attempts=COALESCE(tailor_attempts,0)+? WHERE url=?",
                (str(txt_path), _ts(), result.attempts, job["url"]),
            )
            n += 1
        else:
            conn.execute(
                "UPDATE jobs SET tailor_attempts=COALESCE(tailor_attempts,0)+? WHERE url=?",
                (max(1, result.attempts), job["url"]),
            )
    return n


def run_cover_stage(
    *,
    conn: sqlite3.Connection,
    router: LLMRouter,
    profile: Profile,
    mode: Mode = "normal",
    limit: int = 0,
) -> int:
    """Generate cover letters for rows that flagged cover_required (or always-cover)."""
    sql = (
        "SELECT rowid AS id, url, title, site, location, full_description, cover_required "
        "FROM jobs "
        "WHERE tailored_resume_path IS NOT NULL "
        "  AND cover_letter_path IS NULL "
        "  AND COALESCE(cover_attempts, 0) < 3 "
        "  AND (cover_required = 1 OR ? = 1)"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    always = 1 if profile.apply.always_cover_letter else 0
    n = 0
    for row in conn.execute(sql, (always,)).fetchall():
        job = dict(row)
        result = write_cover_letter(router=router, profile=profile, job=job, mode=mode)
        if result.status == "approved" and result.text:
            path = write_bundle_file(int(job["id"]), "cover_letter.txt", result.text)
            conn.execute(
                "UPDATE jobs SET cover_letter_path=?, cover_letter_at=?, "
                "cover_attempts=COALESCE(cover_attempts,0)+? WHERE url=?",
                (str(path), _ts(), result.attempts, job["url"]),
            )
            n += 1
        else:
            conn.execute(
                "UPDATE jobs SET cover_attempts=COALESCE(cover_attempts,0)+? WHERE url=?",
                (max(1, result.attempts), job["url"]),
            )
    return n


def run_render_stage(*, conn: sqlite3.Connection, profile: Profile, template: str = "resume_classic.tex.j2") -> int:
    """Render any tailored .txt resume + cover letter that lacks a PDF sibling."""
    n = 0
    sql = (
        "SELECT rowid AS id, url, title, site, tailored_resume_path, cover_letter_path "
        "FROM jobs WHERE tailored_resume_path IS NOT NULL"
    )
    for row in conn.execute(sql).fetchall():
        job = dict(row)
        bundle = bundle_dir_for(int(job["id"]))
        resume_pdf = bundle / "resume.pdf"
        if not resume_pdf.exists():
            # The tailored JSON has been discarded by this point; we re-render
            # from the textual artefact via a stub data dict so the engine can
            # write *something*. (M11 will persist the JSON alongside the .txt.)
            try:
                render_resume_pdf(
                    bundle_dir=bundle,
                    profile=profile,
                    data={"title": job.get("title", "")},
                    template=template,
                )
                conn.execute(
                    "UPDATE jobs SET latex_template=? WHERE url=?",
                    (template, job["url"]),
                )
                n += 1
            except LatexEngineError as e:
                log.warning("resume render failed for %s: %s", job["url"], e)

        cover_letter_path = job.get("cover_letter_path")
        if cover_letter_path and not (bundle / "cover_letter.pdf").exists():
            with open(cover_letter_path, encoding="utf-8") as f:
                letter_text = f.read()
            try:
                render_cover_letter_pdf(
                    bundle_dir=bundle,
                    profile=profile,
                    letter_text=letter_text,
                    job=job,
                )
            except LatexEngineError as e:
                log.warning("cover render failed for %s: %s", job["url"], e)
    return n


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    stages: Iterable[str],
    *,
    profile: Profile,
    conn: sqlite3.Connection,
    router: LLMRouter | None = None,
    mode: Mode = "normal",
    limit: int = 0,
) -> dict[str, int]:
    """Run the requested ``stages`` sequentially. Returns per-stage counts.

    ``discover`` and ``enrich`` are wired by their own modules; this function
    only handles the score → tailor → cover → render half of the pipeline.
    Streaming mode (§7) is a TODO comment for M11 hardening.
    """
    # TODO(M11): replace this sequential loop with a streaming orchestrator
    # that polls the DB per stage and signals upstream-done via threading.Event.
    requested = list(stages) if stages else list(STAGE_NAMES)
    counts: dict[str, int] = {}
    router = router or LLMRouter(profile)

    if "score" in requested:
        counts["score"] = run_score_stage(conn=conn, router=router, profile=profile, limit=limit)
    if "tailor" in requested:
        counts["tailor"] = run_tailor_stage(conn=conn, router=router, profile=profile, mode=mode, limit=limit)
    if "cover" in requested:
        counts["cover"] = run_cover_stage(conn=conn, router=router, profile=profile, mode=mode, limit=limit)
    if "render" in requested:
        counts["render"] = run_render_stage(conn=conn, profile=profile)
    return counts


__all__: list[str] = [
    "STAGE_NAMES",
    "run",
    "run_cover_stage",
    "run_render_stage",
    "run_score_stage",
    "run_tailor_stage",
]


# Re-export to keep type-checkers quiet about the unused import in this module.
_ = Any
