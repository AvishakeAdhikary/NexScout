"""Coverage tests for `scoring/{judge,cover_letter,render/engine,tailor}`.

Mocks the LLM router so these focus on parsing, retry logic, validator
integration, sanitiser interplay, and the render-engine selection chain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from nexscout.core.profile import Profile
from nexscout.scoring import cover_letter as cl
from nexscout.scoring import judge as judge_mod
from nexscout.scoring import tailor as tailor_mod
from nexscout.scoring.render import engine as render_engine
from nexscout.scoring.render.engine import LatexEngineError, detect_engine, make_jinja_env
from nexscout.scoring.render.latex_filter import currency_fmt, latex_escape


def _profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {"legal": "Jane Q. Public", "pref": "Jane", "email": "j@x.com", "phone": "1"},
            "auth": {"authorized": True, "sponsor": False, "permit": "USC"},
            "exp": {"years": 7, "edu": "BSc CS", "current_title": "SWE", "target_titles": ["Staff"]},
            "skills": {
                "lang": ["Python"],
                "fw": ["FastAPI"],
                "infra": ["Docker"],
                "data": ["Postgres"],
                "tools": ["Git"],
            },
            "facts": {"companies": ["Acme"], "projects": ["Search"], "school": "State U", "metrics": ["38%"]},
            "captcha": {"provider": "capsolver", "api_key": "x"},
        }
    )


class _FakeRouter:
    """Cycle through a queue of pre-canned LLM responses."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def ask(self, _task: str, _messages: Any, **_: Any) -> str:
        if self.calls >= len(self.replies):
            raise RuntimeError("router exhausted")
        out = self.replies[self.calls]
        self.calls += 1
        return out


# ---------------------------------------------------------------------------
# judge.py
# ---------------------------------------------------------------------------


class TestJudge:
    def test_parse_judge_pass(self) -> None:
        text = "VERDICT: PASS\nISSUES: none"
        verdict, issues = judge_mod.parse_judge(text)
        assert verdict == "PASS"
        assert issues == "none"

    def test_parse_judge_fail(self) -> None:
        text = "Some preamble.\nVERDICT: FAIL\nISSUES: invented Java skill"
        verdict, issues = judge_mod.parse_judge(text)
        assert verdict == "FAIL"
        assert "invented" in issues

    def test_parse_judge_unrecognised_returns_fail(self) -> None:
        verdict, issues = judge_mod.parse_judge("nonsense reply")
        assert verdict == "FAIL"
        assert issues == ""

    def test_build_judge_messages_shape(self) -> None:
        msgs = judge_mod.build_judge_messages(_profile(), {"title": "Staff Engineer"}, "tailored resume text")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert "Staff Engineer" in msgs[1]["content"]

    def test_judge_resume_returns_parsed(self) -> None:
        router = _FakeRouter(["VERDICT: PASS\nISSUES: none"])
        verdict, issues = judge_mod.judge_resume(
            router=router,
            profile=_profile(),
            job={"title": "X"},
            tailored_text="x",  # type: ignore[arg-type]
        )
        assert verdict == "PASS"
        assert issues == "none"

    def test_judge_resume_on_router_error_returns_fail(self) -> None:
        class _BadRouter:
            def ask(self, *a: Any, **k: Any) -> str:
                raise ConnectionError("offline")

        verdict, issues = judge_mod.judge_resume(
            router=_BadRouter(),
            profile=_profile(),
            job={},
            tailored_text="",  # type: ignore[arg-type]
        )
        assert verdict == "FAIL"
        assert "offline" in issues


# ---------------------------------------------------------------------------
# cover_letter.py
# ---------------------------------------------------------------------------


class TestCoverLetter:
    def test_strip_preamble(self) -> None:
        text = "Here is the letter:\nDear Hiring Manager,\nI built things.\nJane"
        assert cl.strip_preamble(text).startswith("Dear")

    def test_strip_preamble_already_clean(self) -> None:
        text = "Dear Hiring Manager,\nI built things."
        assert cl.strip_preamble(text).startswith("Dear")

    def test_strip_preamble_empty(self) -> None:
        assert cl.strip_preamble("") == ""

    def test_build_cover_system_prompt_uses_profile(self) -> None:
        p = _profile()
        sys_prompt = cl.build_cover_system_prompt(p)
        assert "Jane" in sys_prompt

    def test_write_cover_letter_approves_clean_letter(self) -> None:
        router = _FakeRouter(
            [
                "Dear Hiring Manager,\n\nI built distributed search systems handling 50M docs daily, "
                "scaling Postgres clusters and reducing p99 latency by 38 percent.\n\n"
                "At Acme, I shipped a Search Indexer that served 10M MAU; "
                "I rebuilt the auth layer cutting reset cycles in half.\n\n"
                "Your platform's scale is exactly the systems work I do.\n\nJane"
            ]
        )
        result = cl.write_cover_letter(
            router=router,  # type: ignore[arg-type]
            profile=_profile(),
            job={"title": "Staff Engineer", "site": "ExampleCo", "full_description": "Build scale things"},
            mode="lenient",
        )
        assert result.status == "approved"
        assert result.text.startswith("Dear")

    def test_write_cover_letter_router_failure_records_error(self) -> None:
        class _Boom:
            def ask(self, *a: Any, **k: Any) -> str:
                raise RuntimeError("router down")

        result = cl.write_cover_letter(
            router=_Boom(),  # type: ignore[arg-type]
            profile=_profile(),
            job={"title": "X"},
            mode="lenient",
            max_retries=1,
        )
        assert result.status == "failed_validation"
        assert any("router down" in e for e in result.errors)


# ---------------------------------------------------------------------------
# tailor.py — assemble + retry loop
# ---------------------------------------------------------------------------


_GOOD_JSON = (
    '{"title":"Staff Engineer","summary":"Built Python services at scale.",'
    '"skills":{"Languages":"Python, SQL","Frameworks":"FastAPI",'
    '"Infra":"Docker, AWS","Data":"Postgres","Tools":"Git"},'
    '"experience":[{"header":"Senior Engineer at Acme","subtitle":"Python | 2020-2024",'
    '"bullets":["Built indexer.","Cut latency 38%."]}],'
    '"projects":[{"header":"Search","subtitle":"Python","bullets":["Indexed 50M docs/day."]}],'
    '"education":"State U | BSc CS"}'
)


class TestTailor:
    def test_assemble_resume_text_contains_required_sections(self) -> None:
        import json

        data = json.loads(_GOOD_JSON)
        text = tailor_mod.assemble_resume_text(data, _profile())
        for section in ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"):
            assert section in text
        assert "Acme" in text

    def test_assemble_handles_missing_lists(self) -> None:
        import json

        bad = json.loads(_GOOD_JSON)
        bad["skills"] = {}
        bad["experience"] = []
        bad["projects"] = []
        out = tailor_mod.assemble_resume_text(bad, _profile())
        assert "TECHNICAL SKILLS" in out
        assert "EXPERIENCE" in out

    def test_tailor_resume_router_failure_keeps_status(self) -> None:
        class _Down:
            def ask(self, *a: Any, **k: Any) -> str:
                raise RuntimeError("offline")

        result = tailor_mod.tailor_resume(
            router=_Down(),  # type: ignore[arg-type]
            profile=_profile(),
            job={"title": "x", "full_description": "..."},
            mode="lenient",
            max_retries=1,
        )
        assert result.status == "failed_validation"
        assert result.attempts == 1

    def test_tailor_resume_bad_json_retries(self) -> None:
        router = _FakeRouter(["not json", "still not json"])
        result = tailor_mod.tailor_resume(
            router=router,  # type: ignore[arg-type]
            profile=_profile(),
            job={"title": "x", "full_description": "..."},
            mode="lenient",
            max_retries=2,
        )
        assert result.status == "failed_validation"
        assert router.calls == 2

    def test_tailor_resume_approves_clean_lenient(self) -> None:
        router = _FakeRouter([_GOOD_JSON])
        result = tailor_mod.tailor_resume(
            router=router,  # type: ignore[arg-type]
            profile=_profile(),
            job={
                "title": "Staff Engineer",
                "site": "Acme",
                "location": "Remote",
                "full_description": "Python at scale",
            },
            mode="lenient",
            run_judge=False,
            max_retries=1,
        )
        assert result.status == "approved"
        assert "EXPERIENCE" in (result.text or "")


# ---------------------------------------------------------------------------
# render/engine.py
# ---------------------------------------------------------------------------


class TestRenderEngine:
    def test_detect_engine_when_none_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(render_engine.shutil, "which", lambda _: None)
        assert detect_engine() is None

    def test_detect_engine_picks_tectonic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            render_engine.shutil, "which", lambda name: "/fake/tectonic" if name == "tectonic" else None
        )
        assert detect_engine() == "tectonic"

    def test_detect_engine_picks_latexmk_when_no_tectonic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(render_engine.shutil, "which", lambda name: "/fake/latexmk" if name == "latexmk" else None)
        assert detect_engine() == "latexmk"

    def test_make_jinja_env_uses_custom_delimiters(self, tmp_path: Path) -> None:
        tpl_dir = tmp_path / "tpl"
        tpl_dir.mkdir()
        (tpl_dir / "demo.tex.j2").write_text("Hello <<name | tex>>!")
        env = make_jinja_env(tpl_dir)
        out = env.get_template("demo.tex.j2").render(name="Jane & Co")
        assert "Hello Jane \\& Co!" in out

    def test_render_resume_pdf_raises_when_no_engine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(render_engine.shutil, "which", lambda _: None)
        with pytest.raises(LatexEngineError):
            render_engine.render_resume_pdf(
                bundle_dir=tmp_path,
                profile=_profile(),
                data={
                    "title": "X",
                    "summary": "Y",
                    "skills": {"Languages": "Python"},
                    "experience": [],
                    "projects": [],
                    "education": "S",
                },
            )

    def test_render_resume_pdf_calls_tectonic(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When tectonic is on PATH, _compile invokes it (we mock the subprocess)."""

        def fake_which(name: str) -> str | None:
            return "/fake/tectonic" if name == "tectonic" else None

        runs: list[list[str]] = []

        def fake_run(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
            runs.append(args)
            # Drop a fake PDF in the output directory.
            outdir = Path(args[args.index("-o") + 1])
            (outdir / "resume.pdf").write_bytes(b"%PDF-1.4")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        monkeypatch.setattr(render_engine.shutil, "which", fake_which)
        monkeypatch.setattr(render_engine.subprocess, "run", fake_run)

        result = render_engine.render_resume_pdf(
            bundle_dir=tmp_path,
            profile=_profile(),
            data={
                "title": "Staff",
                "summary": "Two sentences.",
                "skills": {"Languages": "Python"},
                "experience": [],
                "projects": [],
                "education": "State U",
            },
        )
        assert result.engine == "tectonic"
        assert result.pdf_path.exists()
        assert runs and runs[0][0] == "tectonic"


# ---------------------------------------------------------------------------
# latex_filter.py edge cases
# ---------------------------------------------------------------------------


class TestLatexFilter:
    def test_currency_fmt_int(self) -> None:
        assert "165,000" in currency_fmt(165000)

    def test_currency_fmt_float(self) -> None:
        assert "165,000" in currency_fmt(165000.5)

    def test_currency_fmt_invalid_returns_escaped(self) -> None:
        # Non-numeric falls through to latex_escape.
        out = currency_fmt("N/A")
        assert "N/A" in out

    def test_latex_escape_specials(self) -> None:
        assert latex_escape("&%$#_{}~^\\") == r"\&\%\$\#\_\{\}\textasciitilde{}\textasciicircum{}\textbackslash{}"

    def test_latex_escape_non_string_input(self) -> None:
        assert latex_escape(42) == "42"
