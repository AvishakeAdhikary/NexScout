"""LaTeX render engine + Jinja2 templates (§12.4 of plan.md)."""

from __future__ import annotations

from .engine import (
    LatexEngineError,
    RenderResult,
    detect_engine,
    make_jinja_env,
    render_cover_letter_pdf,
    render_resume_pdf,
)
from .latex_filter import currency_fmt, latex_escape, today_fmt

__all__ = [
    "LatexEngineError",
    "RenderResult",
    "currency_fmt",
    "detect_engine",
    "latex_escape",
    "make_jinja_env",
    "render_cover_letter_pdf",
    "render_resume_pdf",
    "today_fmt",
]
