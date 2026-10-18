"""ECB euro foreign-exchange reference rates (public, daily XML), kept in Postgres."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.infrastructure.db.models import FxRate
from nexscout.infrastructure.fetch import FetchBlocked, FetchFailed, SafeFetcher

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_RATE = re.compile(r"currency='([A-Z]{3})'\s+rate='([0-9.]+)'")
_DAY = re.compile(r"time='(\d{4}-\d{2}-\d{2})'")


def parse_ecb(xml: str) -> tuple[date | None, dict[str, float]]:
    day = _DAY.search(xml)
    return (
        date.fromisoformat(day.group(1)) if day else None,
        {c: float(r) for c, r in _RATE.findall(xml)},
    )


async def refresh(session: AsyncSession, fetcher: SafeFetcher | None = None) -> int:
    """Fetch today's rates (at most once per day). Returns how many were stored."""
    latest = await session.scalar(select(FxRate.as_of).order_by(FxRate.as_of.desc()).limit(1))
    # The ECB publishes once per business day; its date trails today by a day or more.
    if latest is not None and (datetime.now(UTC).date() - latest).days < 1:
        return 0
    fetcher = fetcher or SafeFetcher(respect_robots=False)
    try:
        status, _h, body, _u = await fetcher.request("GET", ECB_DAILY, check_robots=False)
    except (FetchBlocked, FetchFailed):
        return 0
    if status != 200:
        return 0
    day, rates = parse_ecb(body.decode("utf-8", errors="replace"))
    if day is None or not rates:
        return 0
    for cur, rate in rates.items():
        await session.execute(
            insert(FxRate)
            .values(currency=cur, per_eur=rate, as_of=day)
            .on_conflict_do_update(
                index_elements=["currency"], set_={"per_eur": rate, "as_of": day}
            )
        )
    return len(rates)


async def current_rates(session: AsyncSession) -> dict[str, float]:
    rows = await session.execute(select(FxRate.currency, FxRate.per_eur))
    return {c: float(r) for c, r in rows.all()}
