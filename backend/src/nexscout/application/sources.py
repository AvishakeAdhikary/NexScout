"""Opportunity sources a user can use (ADR-0015): the built-in catalog, the user's own sources,
and (tests/demos only) the labelled demo sources. Enabling, adding, testing and importing.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from nexscout.application.actor import Actor
from nexscout.application.audit import record_audit
from nexscout.domain.errors import NotFound, ValidationFailed
from nexscout.domain.geo import normalize_list
from nexscout.infrastructure.db.models import CustomSource, SourceConfig
from nexscout.infrastructure.security.urls import check_outbound_url
from nexscout.integrations.sources.base import SourceAdapter, SourceQuery, SourceSettings
from nexscout.integrations.sources.core import Entry, EntryAdapter, SourceError
from nexscout.integrations.sources.providers import (
    PROVIDERS,
    catalog,
    catalog_entries,
    detect_provider,
    probe,
)
from nexscout.integrations.sources.registry import adapters as demo_adapters

MAX_CUSTOM = 300
KINDS = ("job", "phd")


@dataclass
class SourceInfo:
    adapter: SourceAdapter
    origin: str  # catalog | custom | demo
    provider: str
    category: str
    url: str
    countries: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)


def _catalog_adapters() -> dict[str, SourceInfo]:
    out = {}
    for key, e in catalog_entries().items():
        out[key] = SourceInfo(
            EntryAdapter(e, PROVIDERS[e.provider]),
            "catalog",
            e.provider,
            e.category,
            e.url,
            e.countries,
            e.kinds,
        )
    return out


async def available(session: AsyncSession, actor: Actor) -> dict[str, SourceInfo]:
    """Every source this user can turn on, keyed by source key."""
    out: dict[str, SourceInfo] = {}
    for key, a in demo_adapters().items():
        out[key] = SourceInfo(
            a, "demo", "demo", "demo", "", [], sorted(k.value for k in a.capabilities.kinds)
        )
    out.update(_catalog_adapters())
    for c in await session.scalars(
        select(CustomSource).where(CustomSource.owner_user_id == actor.user_id)
    ):
        if c.provider not in PROVIDERS:
            continue
        e = Entry(
            key=c.key,
            provider=c.provider,
            name=c.name,
            url=c.url,
            config=dict(c.config),
            countries=list(c.countries),
            kinds=list(c.kinds) or ["job"],
            category="custom",
        )
        out[c.key] = SourceInfo(
            EntryAdapter(e, PROVIDERS[c.provider]),
            "custom",
            c.provider,
            "custom",
            c.url,
            list(c.countries),
            list(c.kinds),
        )
    return out


def default_enabled(info: SourceInfo) -> bool:
    """Demo sources are on in demos; catalog sources wait until the user turns them on."""
    return info.origin in ("demo", "custom")


async def set_enabled(session: AsyncSession, actor: Actor, keys: list[str], enabled: bool) -> int:
    known = await available(session, actor)
    missing = [k for k in keys if k not in known]
    if missing:
        raise NotFound(f"Source not found: {missing[0]}")
    for key in keys:
        await session.execute(
            insert(SourceConfig)
            .values(
                id=uuid.uuid4(),
                owner_user_id=actor.user_id,
                adapter_key=key,
                enabled=enabled,
                settings={},
            )
            .on_conflict_do_update(
                constraint="uq_source_configs_owner_key", set_={"enabled": enabled}
            )
        )
    record_audit(
        session,
        "sources.enabled" if enabled else "sources.disabled",
        actor_user_id=actor.user_id,
        meta={"count": len(keys)},
    )
    return len(keys)


def _custom_key(provider: str, cfg: dict[str, Any], url: str) -> str:
    ident = (
        cfg.get("slug")
        or cfg.get("host")
        or cfg.get("tenant")
        or cfg.get("collection")
        or re.sub(r"^https?://", "", url)
    )
    ident = re.sub(r"[^a-z0-9.-]+", "-", str(ident).lower()).strip("-")[:60]
    return f"custom:{provider}:{ident}"


@dataclass
class AddResult:
    key: str
    provider: str
    name: str
    postings: int
    already_in_catalog: bool = False


async def add_custom(
    session: AsyncSession,
    actor: Actor,
    *,
    url: str,
    name: str,
    kinds: list[str],
    countries: list[str],
) -> AddResult:
    url = url.strip()
    # Syntax and IP-literal check here; the fetcher re-checks every resolved address at connect.
    check_outbound_url(url, allow_private=False, resolve=False)
    if any(k not in KINDS for k in kinds):
        raise ValidationFailed("Kinds are job and phd.")
    codes, unknown = normalize_list(countries)
    if unknown:
        raise ValidationFailed(f"Unknown countries: {', '.join(unknown)}")
    # Already in the catalog? Turn that one on instead of duplicating it.
    found = detect_provider(url)
    if found is not None:
        pid, cfg = found
        for key, e in catalog_entries().items():
            if e.provider == pid and e.config == cfg:
                await set_enabled(session, actor, [key], True)
                return AddResult(key, pid, e.name, 0, already_in_catalog=True)
    total = len(
        list(
            await session.scalars(
                select(CustomSource.id).where(CustomSource.owner_user_id == actor.user_id)
            )
        )
    )
    if total >= MAX_CUSTOM:
        raise ValidationFailed(f"You can add up to {MAX_CUSTOM} sources.")
    try:
        pid, cfg, n = await probe(url, name)
    except SourceError as exc:
        raise ValidationFailed(str(exc)) from exc
    key = _custom_key(pid, cfg, url)
    await session.execute(
        insert(CustomSource)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            key=key,
            provider=pid,
            name=(name.strip() or url)[:200],
            url=url,
            config=cfg,
            countries=codes,
            kinds=kinds or ["job"],
        )
        .on_conflict_do_update(
            constraint="uq_custom_sources_owner_key",
            set_={
                "name": (name.strip() or url)[:200],
                "config": cfg,
                "countries": codes,
                "kinds": kinds or ["job"],
            },
        )
    )
    await set_enabled(session, actor, [key], True)
    await _health(session, actor, key, "ok", None, n)
    record_audit(
        session, "source.added", actor_user_id=actor.user_id, meta={"provider": pid, "postings": n}
    )
    return AddResult(key, pid, name or url, n)


async def delete_custom(session: AsyncSession, actor: Actor, key: str) -> None:
    row = await session.scalar(
        select(CustomSource).where(
            CustomSource.owner_user_id == actor.user_id, CustomSource.key == key
        )
    )
    if row is None:
        raise NotFound("Source not found.")
    await session.delete(row)
    cfg = await session.scalar(
        select(SourceConfig).where(
            SourceConfig.owner_user_id == actor.user_id, SourceConfig.adapter_key == key
        )
    )
    if cfg is not None:
        await session.delete(cfg)


async def _health(
    session: AsyncSession, actor: Actor, key: str, status: str, error: str | None, count: int | None
) -> None:
    await session.execute(
        insert(SourceConfig)
        .values(
            id=uuid.uuid4(),
            owner_user_id=actor.user_id,
            adapter_key=key,
            enabled=True,
            settings={},
            last_status=status,
            last_error=error,
            last_count=count,
            last_fetched_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            constraint="uq_source_configs_owner_key",
            set_={
                "last_status": status,
                "last_error": error,
                "last_count": count,
                "last_fetched_at": datetime.now(UTC),
            },
        )
    )


async def record_health(
    session: AsyncSession, actor: Actor, key: str, *, error: str | None, count: int | None
) -> None:
    await _health(session, actor, key, "error" if error else "ok", error, count)


async def test_source(session: AsyncSession, actor: Actor, key: str) -> dict[str, Any]:
    known = await available(session, actor)
    info = known.get(key)
    if info is None:
        raise NotFound("Source not found.")
    try:
        page = await info.adapter.fetch(
            SourceQuery(kinds=info.adapter.capabilities.kinds), None, SourceSettings({})
        )
    except SourceError as exc:
        await record_health(session, actor, key, error=str(exc)[:500], count=None)
        return {"ok": False, "error": str(exc), "postings": 0, "sample": []}
    titles = [str(r.get("title", "")) for r in page.records[:5]]
    await record_health(session, actor, key, error=None, count=len(page.records))
    return {"ok": True, "error": None, "postings": len(page.records), "sample": titles}


@dataclass
class ImportReport:
    enabled_catalog: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    unsupported: list[dict[str, str]] = field(default_factory=list)


async def import_portals(session: AsyncSession, actor: Actor, text: str) -> ImportReport:
    """career-ops `portals.yml`: companies and boards become sources NexScout can read; the rest
    is reported with the reason. No network here: entries are matched by URL pattern only."""
    if len(text) > 2_000_000:
        raise ValidationFailed("That file is too large.")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ValidationFailed("That isn't a valid YAML file.") from exc
    if not isinstance(data, dict):
        raise ValidationFailed("That doesn't look like a career-ops portals.yml file.")
    report = ImportReport()
    catalog_by_cfg = {
        (e.provider, repr(sorted(e.config.items()))): k for k, e in catalog_entries().items()
    }
    rows = [*(data.get("tracked_companies") or []), *(data.get("job_boards") or [])]
    if len(rows) > 1000:
        raise ValidationFailed("At most 1000 entries per import.")
    to_enable: list[str] = []
    for e in rows:
        if not isinstance(e, dict) or e.get("enabled") is False:
            continue
        name = str(e.get("name") or "").strip()[:200]
        url = str(e.get("careers_url") or e.get("api") or "").strip()
        pid = str(e.get("provider") or "")
        if pid and pid in PROVIDERS and not PROVIDERS[pid].detect(url):
            cfg: dict[str, Any] = dict(e.get(pid) or {}) if isinstance(e.get(pid), dict) else {}
            if pid == "getro" and e.get("getro_collection"):
                cfg["collection"] = str(e["getro_collection"])
            found: tuple[str, dict[str, Any]] | None = (pid, cfg)
        else:
            found = detect_provider(str(e.get("api") or "")) or detect_provider(url)
        if found is None:
            report.unsupported.append(
                {
                    "name": name,
                    "url": url,
                    "reason": (
                        "Web search only in career-ops; NexScout reads public boards, "
                        "not search engines."
                        if e.get("scan_method") == "websearch"
                        else f"Provider {pid or 'unknown'} isn't supported yet."
                    ),
                }
            )
            continue
        pid, cfg = found
        ck = catalog_by_cfg.get((pid, repr(sorted(cfg.items()))))
        if ck:
            to_enable.append(ck)
            report.enabled_catalog.append(name)
            continue
        key = _custom_key(pid, cfg, url or name)
        await session.execute(
            insert(CustomSource)
            .values(
                id=uuid.uuid4(),
                owner_user_id=actor.user_id,
                key=key,
                provider=pid,
                name=name or url,
                url=url,
                config=cfg,
                countries=[],
                kinds=["job"],
            )
            .on_conflict_do_nothing(constraint="uq_custom_sources_owner_key")
        )
        to_enable.append(key)
        report.added.append(name)
    if to_enable:
        await session.flush()
        await set_enabled(session, actor, list(dict.fromkeys(to_enable)), True)
    record_audit(
        session,
        "sources.imported",
        actor_user_id=actor.user_id,
        meta={
            "catalog": len(report.enabled_catalog),
            "added": len(report.added),
            "unsupported": len(report.unsupported),
        },
    )
    return report


def manual_only() -> list[dict[str, str]]:
    return list(catalog().get("manual_only") or [])
