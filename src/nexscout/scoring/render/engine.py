"""LaTeX → PDF render engine (§12.4).

Picks the first available command: ``tectonic`` → ``latexmk`` → ``pdflatex``.
Writes the ``.tex``, ``.pdf`` and ``.log`` outputs into the per-application
bundle directory. Raises :class:`LatexEngineError` if no engine succeeds.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from ...core.errors import NexScoutError
from ...core.profile import Profile
from .latex_filter import currency_fmt, latex_escape, today_fmt

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class LatexEngineError(NexScoutError):
    """Raised when every LaTeX engine fails to compile the document."""


@dataclass
class RenderResult:
    pdf_path: Path
    tex_path: Path
    log_path: Path | None
    engine: str


def make_jinja_env(templates_dir: Path | None = None) -> Environment:
    """Build the Jinja2 environment with the §12.4 delimiters and filters."""
    loader = FileSystemLoader(str(templates_dir or TEMPLATES_DIR))
    env = Environment(
        loader=loader,
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["tex"] = latex_escape
    env.filters["money"] = lambda n, c="USD": currency_fmt(n, c)
    env.globals["today"] = today_fmt
    return env


def detect_engine() -> str | None:
    """Return the name of the first available LaTeX engine, or ``None``."""
    for name in ("tectonic", "latexmk", "pdflatex"):
        if shutil.which(name):
            return name
    return None


def _run(cmd: list[str], *, cwd: Path) -> tuple[int, str]:
    log.debug("running: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _compile(tex_path: Path, out_dir: Path) -> tuple[str, Path | None]:
    """Compile ``tex_path`` to PDF in ``out_dir`` using the best available engine."""
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    if shutil.which("tectonic"):
        code, output = _run(
            ["tectonic", "--keep-logs", "-o", str(out_dir), str(tex_path)],
            cwd=out_dir,
        )
        if code == 0:
            return "tectonic", out_dir / (tex_path.stem + ".log")
        errors.append(f"tectonic exit={code}: {output[-400:]}")

    if shutil.which("latexmk"):
        code, output = _run(
            ["latexmk", "-pdf", "-interaction=nonstopmode", f"-outdir={out_dir}", str(tex_path)],
            cwd=out_dir,
        )
        if code == 0:
            return "latexmk", out_dir / (tex_path.stem + ".log")
        errors.append(f"latexmk exit={code}: {output[-400:]}")

    if shutil.which("pdflatex"):
        # pdflatex twice — once to write aux/log, once to resolve refs.
        last_code = -1
        last_output = ""
        for _ in range(2):
            last_code, last_output = _run(
                [
                    "pdflatex",
                    "-interaction=nonstopmode",
                    f"-output-directory={out_dir}",
                    str(tex_path),
                ],
                cwd=out_dir,
            )
            if last_code != 0:
                break
        if last_code == 0:
            return "pdflatex", out_dir / (tex_path.stem + ".log")
        errors.append(f"pdflatex exit={last_code}: {last_output[-400:]}")

    raise LatexEngineError("no LaTeX engine available or all engines failed:\n" + "\n".join(errors))


def _resume_context(profile: Profile, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "me": profile.me,
        "title": data.get("title", ""),
        "summary": data.get("summary", ""),
        "skills": data.get("skills", {}),
        "experience": data.get("experience", []),
        "projects": data.get("projects", []),
        "education": data.get("education", ""),
        "today": date.today().isoformat(),
    }


def render_resume_pdf(
    *,
    bundle_dir: Path,
    profile: Profile,
    data: dict[str, Any],
    template: str = "resume_classic.tex.j2",
) -> RenderResult:
    """Render a tailored-resume JSON document to a PDF in ``bundle_dir``."""
    env = make_jinja_env()
    tex_source = env.get_template(template).render(**_resume_context(profile, data))

    bundle_dir.mkdir(parents=True, exist_ok=True)
    tex_path = bundle_dir / "resume.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    engine, log_path = _compile(tex_path, bundle_dir)
    pdf_path = bundle_dir / "resume.pdf"
    if not pdf_path.exists():
        raise LatexEngineError(f"{engine} reported success but no PDF at {pdf_path}")
    return RenderResult(pdf_path=pdf_path, tex_path=tex_path, log_path=log_path, engine=engine)


def render_cover_letter_pdf(
    *,
    bundle_dir: Path,
    profile: Profile,
    letter_text: str,
    job: dict[str, Any],
    template: str = "cover_letter.tex.j2",
) -> RenderResult:
    """Render the plain-text cover letter to a PDF inside ``bundle_dir``."""
    env = make_jinja_env()
    context = {
        "me": profile.me,
        "letter": letter_text,
        "job": job,
        "today": date.today().isoformat(),
    }
    tex_source = env.get_template(template).render(**context)

    bundle_dir.mkdir(parents=True, exist_ok=True)
    tex_path = bundle_dir / "cover_letter.tex"
    tex_path.write_text(tex_source, encoding="utf-8")
    engine, log_path = _compile(tex_path, bundle_dir)
    pdf_path = bundle_dir / "cover_letter.pdf"
    if not pdf_path.exists():
        raise LatexEngineError(f"{engine} reported success but no PDF at {pdf_path}")
    return RenderResult(pdf_path=pdf_path, tex_path=tex_path, log_path=log_path, engine=engine)
