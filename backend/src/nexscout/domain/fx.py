"""Currency conversion with ECB euro reference rates (pure).

Rates are "units of currency per 1 EUR" as the European Central Bank publishes them daily
(infrastructure/fx.py fetches and stores them). Without a rate, conversion returns None and the
caller reports "can't compare" instead of guessing.
"""

from __future__ import annotations


def convert(amount: float, from_cur: str, to_cur: str, rates: dict[str, float]) -> float | None:
    f, t = from_cur.upper(), to_cur.upper()
    if f == t:
        return amount
    per_eur = {"EUR": 1.0, **{k.upper(): v for k, v in rates.items()}}
    if f not in per_eur or t not in per_eur or per_eur[f] <= 0:
        return None
    return amount / per_eur[f] * per_eur[t]
