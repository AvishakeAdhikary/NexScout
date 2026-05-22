"""latex_escape + currency_fmt + Jinja2 env wiring."""

from __future__ import annotations

from nexscout.scoring.render.engine import make_jinja_env
from nexscout.scoring.render.latex_filter import currency_fmt, latex_escape


def test_escape_special_characters() -> None:
    assert latex_escape("& % $ # _ { } ~ ^") == (r"\& \% \$ \# \_ \{ \} \textasciitilde{} \textasciicircum{}")


def test_escape_backslash() -> None:
    assert latex_escape("path\\to\\file") == r"path\textbackslash{}to\textbackslash{}file"


def test_escape_plain_text_unchanged() -> None:
    assert latex_escape("Hello world 2024") == "Hello world 2024"


def test_currency_fmt_thousands_separator() -> None:
    assert currency_fmt(150000, "USD") == r"\$150,000"
    assert currency_fmt(2100000, "CAD") == r"\$2,100,000"


def test_jinja_env_uses_custom_delimiters_and_filters_render_text() -> None:
    env = make_jinja_env()
    tmpl = env.from_string("Hello << name | tex >>, pay << amount | money('USD') >>")
    out = tmpl.render(name="Jane & Co.", amount=150000)
    assert r"Jane \& Co." in out
    assert r"\$150,000" in out


def test_jinja_env_block_delimiters() -> None:
    env = make_jinja_env()
    tmpl = env.from_string("<% for x in items %><< x | tex >>;<% endfor %>")
    assert tmpl.render(items=["a", "b%"]) == "a;b\\%;"
