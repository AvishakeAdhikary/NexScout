"""LaTeX-safe Jinja2 filters used by resume + cover letter templates.

Escapes the dangerous LaTeX characters ``& % $ # _ { } ~ ^ \\`` exactly as
required by §12.4. Two additional helpers provide currency and date
formatting.
"""

from __future__ import annotations

from datetime import date

_ESCAPE_MAP: dict[str, str] = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(value: object) -> str:
    """Escape ``value`` so it is safe to drop into a LaTeX template body."""
    if value is None:
        return ""
    text = str(value)
    out: list[str] = []
    for ch in text:
        if ch in _ESCAPE_MAP:
            out.append(_ESCAPE_MAP[ch])
        else:
            out.append(ch)
    return "".join(out)


def currency_fmt(amount: object, currency: str = "USD") -> str:
    """Render a number as ``${amount:,}`` with the currency prefix."""
    try:
        n = int(amount)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        try:
            n = int(float(amount))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return latex_escape(str(amount))
    symbol = {"USD": "\\$", "CAD": "\\$", "EUR": "\\euro{}", "GBP": "\\pounds{}"}.get(currency, latex_escape(currency))
    return f"{symbol}{n:,}"


def today_fmt(fmt: str = "%B %d, %Y") -> str:
    """Today's date formatted via ``date.today().strftime``."""
    return date.today().strftime(fmt)
