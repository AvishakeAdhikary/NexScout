"""Tests for ``scoring.render.engine`` — Jinja + subprocess wrapper."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexscout.scoring.render import engine as eng
from nexscout.scoring.render.engine import (
    LatexEngineError,
    RenderResult,
    detect_engine,
    make_jinja_env,
)


def test_make_jinja_env_has_filters() -> None:
    env = make_jinja_env()
    assert "tex" in env.filters
    assert "money" in env.filters


def test_detect_engine_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert detect_engine() is None


def test_detect_engine_pdflatex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None)
    assert detect_engine() == "pdflatex"


def test_compile_raises_when_no_engine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(LatexEngineError):
        eng._compile(tmp_path / "x.tex", tmp_path)


def test_compile_tectonic_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/tectonic" if name == "tectonic" else None)
    monkeypatch.setattr(eng, "_run", lambda cmd, *, cwd: (0, "ok"))
    engine_name, _log_path = eng._compile(tmp_path / "x.tex", tmp_path)
    assert engine_name == "tectonic"


def test_compile_latexmk_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/latexmk" if name == "latexmk" else None)
    monkeypatch.setattr(eng, "_run", lambda cmd, *, cwd: (0, "ok"))
    engine_name, _ = eng._compile(tmp_path / "x.tex", tmp_path)
    assert engine_name == "latexmk"


def test_compile_pdflatex_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None)
    monkeypatch.setattr(eng, "_run", lambda cmd, *, cwd: (0, "ok"))
    engine_name, _ = eng._compile(tmp_path / "x.tex", tmp_path)
    assert engine_name == "pdflatex"


def test_compile_pdflatex_failure_aggregates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pdflatex" if name == "pdflatex" else None)
    monkeypatch.setattr(eng, "_run", lambda cmd, *, cwd: (1, "syntax error"))
    with pytest.raises(LatexEngineError):
        eng._compile(tmp_path / "x.tex", tmp_path)


def test_render_resume_pdf_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stub _compile and write a dummy PDF so the full path is exercised."""
    pdf = tmp_path / "resume.pdf"

    def _fake_compile(tex_path: Path, out_dir: Path) -> tuple[str, Path | None]:
        pdf.write_bytes(b"%PDF")
        return "tectonic", out_dir / "resume.log"

    monkeypatch.setattr(eng, "_compile", _fake_compile)

    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    res = eng.render_resume_pdf(
        bundle_dir=tmp_path,
        profile=p,
        data={"title": "Eng", "summary": "Hi", "skills": {}, "experience": [], "projects": [], "education": ""},
    )
    assert isinstance(res, RenderResult)


def test_render_resume_pdf_missing_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If _compile succeeds but no PDF is written, raise LatexEngineError."""
    monkeypatch.setattr(eng, "_compile", lambda tex, out: ("tectonic", out / "x.log"))
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    with pytest.raises(LatexEngineError):
        eng.render_resume_pdf(
            bundle_dir=tmp_path,
            profile=p,
            data={"title": "Eng", "summary": "", "skills": {}, "experience": [], "projects": [], "education": ""},
        )


def test_render_cover_letter_pdf_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf = tmp_path / "cover_letter.pdf"

    def _fake_compile(tex_path: Path, out_dir: Path) -> tuple[str, Path | None]:
        pdf.write_bytes(b"%PDF")
        return "tectonic", out_dir / "cover_letter.log"

    monkeypatch.setattr(eng, "_compile", _fake_compile)

    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    res = eng.render_cover_letter_pdf(
        bundle_dir=tmp_path,
        profile=p,
        letter_text="Dear team,",
        job={"title": "Eng", "site": "Acme"},
    )
    assert isinstance(res, RenderResult)


def test_render_cover_letter_pdf_missing_pdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(eng, "_compile", lambda tex, out: ("tectonic", None))
    from nexscout.core.profile import Profile

    p = Profile.model_validate({"me": {"legal": "x", "pref": "x", "email": "e@x.com", "phone": "1"}})
    with pytest.raises(LatexEngineError):
        eng.render_cover_letter_pdf(
            bundle_dir=tmp_path, profile=p, letter_text="X", job={"title": "Eng"}
        )


def test_run_returns_subprocess_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        eng.subprocess, "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
    )
    code, out = eng._run(["echo", "x"], cwd=tmp_path)
    assert code == 0
    assert "ok" in out
