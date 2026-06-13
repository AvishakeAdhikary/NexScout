"""Pipeline orchestrator (§7 of plan.md).

Sequential ``run(stages, profile, db)`` wires the six stages together end-to-end.
When ``stream=True`` each stage runs in its own thread, communicating via
:class:`threading.Event` signals — upstream stages set their ``done`` flag and
downstream workers poll the DB for new pending rows (poll interval
``STREAM_POLL_INTERVAL = 10s`` per §7).

The render stage reads the JSON document persisted alongside the tailored
``.txt`` (``resume.json``) so the LaTeX engine receives the full structured
resume instead of a one-field placeholder. Legacy rows that lack
``resume.json`` are recovered via :func:`parse_resume_txt`.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .core.bundle import bundle_dir_for, write_bundle_file
from .core.profile import Profile
from .llm.router import LLMRouter
from .scoring.cover_letter import write_cover_letter
from .scoring.render.engine import LatexEngineError, render_cover_letter_pdf, render_resume_pdf
from .scoring.scorer import persist_score, score_job
from .scoring.tailor import tailor_resume
from .scoring.validator import Mode

if TYPE_CHECKING:
    from .browser.driver import BrowserFactory

log = logging.getLogger(__name__)

STAGE_NAMES: tuple[str, ...] = ("discover", "enrich", "score", "tailor", "cover", "render")

#: §7 streaming poll interval — each stage worker sleeps this long when its
#: pending queue is empty but the upstream stage isn't done yet.
STREAM_POLL_INTERVAL: float = 10.0


def _ts() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Discover stage — wires the four discovery engines (§8)
# ---------------------------------------------------------------------------


def run_discover_stage(
    *,
    conn: sqlite3.Connection,
    profile: Profile,
    router: LLMRouter | None = None,
    limit_per_engine: int = 0,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Run each available discovery engine and return the new-row count.

    Engines that aren't installed (e.g. ``python-jobspy`` is optional) are
    skipped. Each engine writes to ``jobs`` via the standard ``insert_jobs``
    helper so duplicates are silently dropped.

    ``should_abort`` is checked **between** engines so discover honours its
    per-stage time budget — the cheap API engines (jobspy/workday/websearch)
    run first, and the slow browser+LLM engines (browser-websearch,
    smartextract) are skipped once the budget is spent, so discover can never
    starve the downstream stages.
    """
    total = 0
    _ = limit_per_engine  # reserved for engines that don't yet honour per-engine caps

    def _stop() -> bool:
        if should_abort is not None and should_abort():
            log.info("discover: time budget reached — skipping remaining engines")
            return True
        return False

    try:
        from .discovery import jobspy as _jobspy_mod
    except ImportError:
        log.info("discovery.jobspy unavailable; skipping")
    else:
        try:
            new, _dup = _jobspy_mod.run_jobspy(profile, conn=conn)
            total += int(new)
        except Exception as e:
            log.warning("jobspy engine failed: %s", e)

    if not _stop():
        try:
            from .discovery import workday as _workday_mod
        except ImportError:
            log.info("discovery.workday unavailable; skipping")
        else:
            try:
                new, _dup = _workday_mod.run_workday(profile, conn=conn)
                total += int(new)
            except Exception as e:
                log.warning("workday engine failed: %s", e)

    if not _stop():
        try:
            from .discovery import websearch as _websearch_mod
        except ImportError:
            log.info("discovery.websearch unavailable; skipping")
        else:
            try:
                new, _dup = _websearch_mod.run_websearch(profile, conn=conn)
                total += int(new)
            except Exception as e:
                log.warning("websearch engine failed: %s", e)

            # Browser-driven WebSearch (Google + DuckDuckGo) — the no-API-key
            # path that keeps working when JobSpy is IP-rate-limited. Needs an
            # undetected Chrome; on hosts without one it returns (0, 0).
            if not _stop():
                try:
                    from .browser.driver import UndetectedFactory

                    new, _dup = _websearch_mod.run_browser_websearch(
                        profile, conn=conn, router=router, limit=limit_per_engine, browser_factory=UndetectedFactory()
                    )
                    total += int(new)
                except Exception as e:
                    log.warning("browser websearch engine failed: %s", e)

    # SmartExtract needs a router + a browser; it's the slowest engine (a
    # browser + LLM session per employer), so it runs last and only if the
    # discover time budget hasn't been spent.
    if router is not None and not _stop():
        try:
            from .discovery import smartextract as _smart_mod
        except ImportError:
            log.info("discovery.smartextract unavailable; skipping")
        else:
            try:
                runner = getattr(_smart_mod, "run_smartextract", None)
                if runner is not None:
                    new, _dup = runner(profile, conn=conn, router=router)
                    total += int(new)
            except Exception as e:
                log.warning("smartextract engine failed: %s", e)

    return total


# ---------------------------------------------------------------------------
# Enrich stage — wires enrichment.detail (§9)
# ---------------------------------------------------------------------------


def run_enrich_stage(
    *,
    conn: sqlite3.Connection,
    profile: Profile,
    router: LLMRouter | None = None,
    browser_factory: BrowserFactory | None = None,
    limit: int = 0,
    on_progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Enrich pending rows; returns the number of rows that got a description."""
    from .enrichment import detail as _detail_mod

    factory = browser_factory
    if factory is None:
        try:
            from .browser.driver import UndetectedFactory

            factory = UndetectedFactory()
        except Exception as e:
            log.info("enrich: no browser factory available (%s); skipping", e)
            return 0

    sql = (
        "SELECT rowid AS id, url, title, site, application_url FROM jobs "
        "WHERE detail_scraped_at IS NULL AND site NOT IN ('glassdoor','google','Workopolis')"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    total = len(rows)
    n = 0
    for i, row in enumerate(rows):
        if should_abort is not None and should_abort():
            break
        job = dict(row)
        try:
            result = _detail_mod.enrich_row(row=job, factory=factory, router=router, headless=profile.apply.headless)
        except Exception as e:
            log.warning("enrich row failed for %s: %s", job.get("url"), e)
            _detail_mod.persist_enrichment_error(conn, job["url"], str(e)[:400])
        else:
            if result is None:
                _detail_mod.persist_enrichment_error(conn, job["url"], "no_extractor_succeeded")
            else:
                _detail_mod.persist_enrichment(conn, job["url"], result)
                n += 1
        if on_progress is not None:
            on_progress(i + 1, total)
    return n


# ---------------------------------------------------------------------------
# Per-row stages (score / tailor / cover / render)
# ---------------------------------------------------------------------------


def run_score_stage(
    *,
    conn: sqlite3.Connection,
    router: LLMRouter,
    profile: Profile,
    limit: int = 0,
    on_progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Score every row with ``full_description IS NOT NULL AND fit_score IS NULL``.

    ``on_progress(done, total)`` is called after each row and ``should_abort()``
    is checked before each row, so a caller (the tick) can report live progress
    and honour a stop request without changing the sequential execution model.
    """
    sql = (
        "SELECT rowid AS id, url, title, site, location, full_description "
        "FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    total = len(rows)
    n = 0
    for i, row in enumerate(rows):
        if should_abort is not None and should_abort():
            break
        job = dict(row)
        score, reasoning = score_job(router, profile, job)
        persist_score(conn, job["url"], score, reasoning)
        n += 1
        if on_progress is not None:
            on_progress(i + 1, total)
    return n


def run_tailor_stage(
    *,
    conn: sqlite3.Connection,
    router: LLMRouter,
    profile: Profile,
    mode: Mode = "normal",
    limit: int = 0,
    on_progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Tailor every eligible row; persist text + JSON + path; bump attempts."""
    sql = (
        "SELECT rowid AS id, url, title, site, location, full_description, fit_score "
        "FROM jobs "
        "WHERE fit_score >= ? "
        "  AND tailored_resume_path IS NULL "
        "  AND COALESCE(tailor_attempts, 0) < 5"
    )
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql, (profile.search.min_score,)).fetchall()
    total = len(rows)
    n = 0
    for i, row in enumerate(rows):
        if should_abort is not None and should_abort():
            break
        job = dict(row)
        result = tailor_resume(router=router, profile=profile, job=job, mode=mode)
        if result.status == "approved" and result.text:
            txt_path = write_bundle_file(int(job["id"]), "resume.txt", result.text)
            # Persist the structured tailored JSON alongside the text so the
            # render stage can use the full document instead of a stub dict.
            if result.data is not None:
                write_bundle_file(
                    int(job["id"]),
                    "resume.json",
                    json.dumps(result.data, indent=2, ensure_ascii=False),
                )
            write_bundle_file(
                int(job["id"]),
                "_REPORT.json",
                json.dumps(
                    {
                        "attempts": result.attempts,
                        "judge_verdict": result.judge_verdict,
                        "judge_issues": result.judge_issues,
                    },
                    indent=2,
                ),
            )
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
        if on_progress is not None:
            on_progress(i + 1, total)
    return n


def run_cover_stage(
    *,
    conn: sqlite3.Connection,
    router: LLMRouter,
    profile: Profile,
    mode: Mode = "normal",
    limit: int = 0,
    on_progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
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
    rows = conn.execute(sql, (always,)).fetchall()
    total = len(rows)
    n = 0
    for i, row in enumerate(rows):
        if should_abort is not None and should_abort():
            break
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
        if on_progress is not None:
            on_progress(i + 1, total)
    return n


# ---------------------------------------------------------------------------
# Resume-text recovery
# ---------------------------------------------------------------------------


_TXT_SECTIONS = ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_SKILL_LINE_RE = re.compile(r"^([A-Za-z ]+):\s*(.+)$")


def parse_resume_txt(text: str) -> dict[str, Any]:
    """Recover a structured resume dict from an assembled resume ``.txt``.

    Used as a fallback when ``resume.json`` is missing (legacy rows). Best-effort:
    pulls ``title``, ``summary``, ``skills``, ``experience``, ``projects``,
    ``education`` from the §11 assembled-resume format. Unknown lines are kept
    as part of the previous bullet group.
    """
    data: dict[str, Any] = {
        "title": "",
        "summary": "",
        "skills": {},
        "experience": [],
        "projects": [],
        "education": "",
    }
    if not text:
        return data
    lines = [ln.rstrip() for ln in text.splitlines()]

    # Header — second non-empty line is the title (line 0 = legal name).
    nonempty = [ln for ln in lines if ln.strip()]
    if len(nonempty) >= 2:
        data["title"] = nonempty[1].strip()

    # Walk sections.
    section: str | None = None
    summary_parts: list[str] = []
    skills: dict[str, str] = {}
    cur_section_list: list[dict[str, Any]] = []
    cur_item: dict[str, Any] | None = None
    edu_parts: list[str] = []

    def flush_item() -> None:
        nonlocal cur_item
        if cur_item is not None:
            cur_section_list.append(cur_item)
        cur_item = None

    for raw in lines:
        ln = raw.strip()
        upper = ln.upper()
        if upper in _TXT_SECTIONS:
            # commit pending item before changing section
            if section in ("EXPERIENCE", "PROJECTS"):
                flush_item()
                if section == "EXPERIENCE":
                    data["experience"] = list(cur_section_list)
                else:
                    data["projects"] = list(cur_section_list)
                cur_section_list = []
            section = upper
            continue
        if section == "SUMMARY":
            if ln:
                summary_parts.append(ln)
        elif section == "TECHNICAL SKILLS":
            m = _SKILL_LINE_RE.match(ln)
            if m:
                skills[m.group(1).strip()] = m.group(2).strip()
        elif section in ("EXPERIENCE", "PROJECTS"):
            bullet = _BULLET_RE.match(ln)
            if bullet:
                if cur_item is None:
                    cur_item = {"header": "", "subtitle": "", "bullets": []}
                cur_item["bullets"].append(bullet.group(1))
            elif not ln:
                # blank line ends the current item
                flush_item()
            elif cur_item is None:
                cur_item = {"header": ln, "subtitle": "", "bullets": []}
            elif not cur_item["subtitle"] and cur_item["bullets"] == []:
                cur_item["subtitle"] = ln
            else:
                flush_item()
                cur_item = {"header": ln, "subtitle": "", "bullets": []}
        elif section == "EDUCATION" and ln:
            edu_parts.append(ln)

    # Final flush for the last section.
    if section in ("EXPERIENCE", "PROJECTS"):
        flush_item()
        if section == "EXPERIENCE":
            data["experience"] = list(cur_section_list)
        else:
            data["projects"] = list(cur_section_list)

    data["summary"] = " ".join(summary_parts).strip()
    data["skills"] = skills
    data["education"] = " | ".join(edu_parts).strip()
    return data


def run_render_stage(
    *,
    conn: sqlite3.Connection,
    profile: Profile,
    template: str = "resume_classic.tex.j2",
    on_progress: Callable[[int, int], None] | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> int:
    """Render any tailored .txt resume + cover letter that lacks a PDF sibling."""
    n = 0
    sql = (
        "SELECT rowid AS id, url, title, site, tailored_resume_path, cover_letter_path "
        "FROM jobs WHERE tailored_resume_path IS NOT NULL"
    )
    rows = conn.execute(sql).fetchall()
    total = len(rows)
    for i, row in enumerate(rows):
        if should_abort is not None and should_abort():
            break
        job = dict(row)
        bundle = bundle_dir_for(int(job["id"]))
        resume_pdf = bundle / "resume.pdf"
        if not resume_pdf.exists():
            data = _load_resume_data(bundle, job)
            try:
                render_resume_pdf(
                    bundle_dir=bundle,
                    profile=profile,
                    data=data,
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
            letter_text: str | None = None
            try:
                with open(cover_letter_path, encoding="utf-8") as f:
                    letter_text = f.read()
            except OSError as e:
                log.warning("cover letter file unreadable for %s: %s", job["url"], e)
            if letter_text is not None:
                try:
                    render_cover_letter_pdf(
                        bundle_dir=bundle,
                        profile=profile,
                        letter_text=letter_text,
                        job=job,
                    )
                except LatexEngineError as e:
                    log.warning("cover render failed for %s: %s", job["url"], e)
        if on_progress is not None:
            on_progress(i + 1, total)
    return n


def _load_resume_data(bundle: Path, job: dict[str, Any]) -> dict[str, Any]:
    """Load the structured resume document for a job, falling back to txt parse."""
    json_path = bundle / "resume.json"
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError) as e:
            log.warning("resume.json unreadable for %s: %s", job.get("url"), e)
    # Legacy row: recover from the assembled .txt sibling.
    txt_path_str = job.get("tailored_resume_path") or ""
    if txt_path_str:
        txt_path = Path(txt_path_str)
        try:
            text = txt_path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("resume.txt unreadable for %s: %s", job.get("url"), e)
            text = ""
        if text:
            data = parse_resume_txt(text)
            data.setdefault("title", str(job.get("title") or ""))
            return data
    # Last resort: title-only stub. (Should never happen — tailored_resume_path
    # is set only after the tailor stage writes the .txt.)
    return {
        "title": str(job.get("title") or ""),
        "summary": "",
        "skills": {},
        "experience": [],
        "projects": [],
        "education": "",
    }


# ---------------------------------------------------------------------------
# Streaming pipeline (§7) — each stage runs in its own thread
# ---------------------------------------------------------------------------


def _pending_count(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return 0
    val = row[0]
    return int(val) if val is not None else 0


def _streaming_stage_loop(
    *,
    name: str,
    pending_sql: str,
    pending_params: tuple[Any, ...],
    do_batch: Callable[[], int],
    upstream_done: threading.Event,
    stop: threading.Event,
    done: threading.Event,
    counts: dict[str, int],
    conn: sqlite3.Connection,
    poll_interval: float,
) -> None:
    """Generic streaming worker — pending → batch → poll → exit on upstream done."""
    counts.setdefault(name, 0)
    try:
        while not stop.is_set():
            pending = _pending_count(conn, pending_sql, pending_params)
            if pending > 0:
                produced = do_batch()
                counts[name] += int(produced or 0)
                continue
            if upstream_done.is_set():
                break
            stop.wait(poll_interval)
    except Exception:
        log.exception("streaming stage %s crashed", name)
    finally:
        done.set()


def _run_streaming(
    *,
    profile: Profile,
    conn: sqlite3.Connection,
    router: LLMRouter,
    mode: Mode,
    limit: int,
    requested: list[str],
    poll_interval: float,
) -> dict[str, int]:
    """Streaming variant of :func:`run` — see module docstring."""
    counts: dict[str, int] = {n: 0 for n in STAGE_NAMES}
    stop = threading.Event()

    discover_done = threading.Event()
    enrich_done = threading.Event()
    score_done = threading.Event()
    tailor_done = threading.Event()
    cover_done = threading.Event()
    render_done = threading.Event()

    threads: list[threading.Thread] = []

    # Discover runs once per tick (sub-engines do their own crawl), then signals done.
    def discover_once() -> None:
        try:
            if "discover" in requested:
                counts["discover"] = run_discover_stage(
                    conn=conn, profile=profile, router=router, limit_per_engine=limit
                )
        finally:
            discover_done.set()

    threads.append(threading.Thread(target=discover_once, name="ns-discover", daemon=True))

    if "enrich" in requested:
        threads.append(
            threading.Thread(
                target=_streaming_stage_loop,
                kwargs={
                    "name": "enrich",
                    "pending_sql": (
                        "SELECT COUNT(*) FROM jobs WHERE detail_scraped_at IS NULL "
                        "AND site NOT IN ('glassdoor','google','Workopolis')"
                    ),
                    "pending_params": (),
                    "do_batch": lambda: run_enrich_stage(conn=conn, profile=profile, router=router, limit=limit or 5),
                    "upstream_done": discover_done,
                    "stop": stop,
                    "done": enrich_done,
                    "counts": counts,
                    "conn": conn,
                    "poll_interval": poll_interval,
                },
                name="ns-enrich",
                daemon=True,
            )
        )
    else:
        enrich_done.set()

    if "score" in requested:
        threads.append(
            threading.Thread(
                target=_streaming_stage_loop,
                kwargs={
                    "name": "score",
                    "pending_sql": (
                        "SELECT COUNT(*) FROM jobs WHERE full_description IS NOT NULL AND fit_score IS NULL"
                    ),
                    "pending_params": (),
                    "do_batch": lambda: run_score_stage(conn=conn, router=router, profile=profile, limit=limit or 10),
                    "upstream_done": enrich_done,
                    "stop": stop,
                    "done": score_done,
                    "counts": counts,
                    "conn": conn,
                    "poll_interval": poll_interval,
                },
                name="ns-score",
                daemon=True,
            )
        )
    else:
        score_done.set()

    if "tailor" in requested:
        tailor_sql = (
            "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? "
            "AND tailored_resume_path IS NULL AND COALESCE(tailor_attempts,0) < 5"
        )
        threads.append(
            threading.Thread(
                target=_streaming_stage_loop,
                kwargs={
                    "name": "tailor",
                    "pending_sql": tailor_sql,
                    "pending_params": (profile.search.min_score,),
                    "do_batch": lambda: run_tailor_stage(
                        conn=conn, router=router, profile=profile, mode=mode, limit=limit or 3
                    ),
                    "upstream_done": score_done,
                    "stop": stop,
                    "done": tailor_done,
                    "counts": counts,
                    "conn": conn,
                    "poll_interval": poll_interval,
                },
                name="ns-tailor",
                daemon=True,
            )
        )
    else:
        tailor_done.set()

    if "cover" in requested:
        cover_sql = (
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
            "AND cover_letter_path IS NULL AND COALESCE(cover_attempts,0) < 3 "
            "AND (cover_required = 1 OR ? = 1)"
        )
        threads.append(
            threading.Thread(
                target=_streaming_stage_loop,
                kwargs={
                    "name": "cover",
                    "pending_sql": cover_sql,
                    "pending_params": (1 if profile.apply.always_cover_letter else 0,),
                    "do_batch": lambda: run_cover_stage(
                        conn=conn, router=router, profile=profile, mode=mode, limit=limit or 3
                    ),
                    "upstream_done": tailor_done,
                    "stop": stop,
                    "done": cover_done,
                    "counts": counts,
                    "conn": conn,
                    "poll_interval": poll_interval,
                },
                name="ns-cover",
                daemon=True,
            )
        )
    else:
        cover_done.set()

    if "render" in requested:
        render_sql = (
            "SELECT COUNT(*) FROM jobs WHERE tailored_resume_path IS NOT NULL "
            "AND (bundle_dir IS NULL OR bundle_dir != '')"
        )
        threads.append(
            threading.Thread(
                target=_streaming_stage_loop,
                kwargs={
                    "name": "render",
                    "pending_sql": render_sql,
                    "pending_params": (),
                    "do_batch": lambda: run_render_stage(conn=conn, profile=profile),
                    "upstream_done": cover_done,
                    "stop": stop,
                    "done": render_done,
                    "counts": counts,
                    "conn": conn,
                    "poll_interval": poll_interval,
                },
                name="ns-render",
                daemon=True,
            )
        )
    else:
        render_done.set()

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    return counts


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
    stream: bool = False,
    browser_factory: BrowserFactory | None = None,
    poll_interval: float | None = None,
) -> dict[str, int]:
    """Run the requested ``stages`` sequentially. Returns per-stage counts.

    When ``stream=True`` each stage runs in its own thread, signalling
    completion via :class:`threading.Event` so downstream stages can drain
    their queues without waiting for upstream to finish first.
    """
    requested = list(stages) if stages else list(STAGE_NAMES)
    if requested == ["all"]:
        requested = list(STAGE_NAMES)
    router = router or LLMRouter(profile)

    if stream:
        return _run_streaming(
            profile=profile,
            conn=conn,
            router=router,
            mode=mode,
            limit=limit,
            requested=requested,
            poll_interval=float(poll_interval if poll_interval is not None else STREAM_POLL_INTERVAL),
        )

    counts: dict[str, int] = {}
    if "discover" in requested:
        counts["discover"] = run_discover_stage(conn=conn, profile=profile, router=router, limit_per_engine=limit)
    if "enrich" in requested:
        counts["enrich"] = run_enrich_stage(
            conn=conn, profile=profile, router=router, browser_factory=browser_factory, limit=limit
        )
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
    "STREAM_POLL_INTERVAL",
    "parse_resume_txt",
    "run",
    "run_cover_stage",
    "run_discover_stage",
    "run_enrich_stage",
    "run_render_stage",
    "run_score_stage",
    "run_tailor_stage",
]
