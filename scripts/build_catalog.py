"""Build backend/src/nexscout/integrations/sources/catalog.yaml (run when updating the catalog).

    uv run --project backend python scripts/build_catalog.py <career-ops checkout> \
        [--discover] [--verify]

--discover (live) finds the ATS board behind branded careers pages; --verify (live) reads every
entry once and moves boards that no longer exist to `unsupported`, so the catalog never ships
dead entries. Release catalogs are built with both.

Inputs:
- career-ops' templates/portals.example.yml (MIT) at the commit in UPSTREAM_SHA: every
  `tracked_companies` and `job_boards` entry is mapped to a NexScout provider through the same
  `detect()` the app uses. Entries NexScout can't read through a public API or feed (web-search-only
  entries, providers not ported yet) go to `unsupported` with the reason, never silently dropped.
- EU_ADDITIONS below: European / Finnish employers and universities, each verified live (boards
  that returned postings on 2026-10-18).
- BOARDS below: the board-wide sources (one per provider).
- MANUAL below: well-known boards NexScout must not automate (terms, robots.txt or bot blocking).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nexscout.integrations.sources.providers import (  # noqa: E402
    PROVIDERS,
    detect_provider,
    probe,
)

UPSTREAM_SHA = "340a53b1bd4e9728237c6b964f3828589b1fc14e"
OUT = ROOT / "backend/src/nexscout/integrations/sources/catalog.yaml"

EU_ADDITIONS = [
    # name, url, countries, kinds
    ("Wolt", "https://job-boards.greenhouse.io/wolt", ["FI"], ["job"]),
    ("Oura", "https://job-boards.greenhouse.io/oura", ["FI"], ["job"]),
    ("KONE", "https://kone.wd3.myworkdayjobs.com/en-US/Careers", ["FI"], ["job"]),
    ("Nordcloud", "https://nordcloud-career.breezy.hr", ["FI"], ["job"]),
    ("Helsing", "https://job-boards.greenhouse.io/helsing", ["DE", "GB", "FR"], ["job"]),
    ("DeepL", "https://jobs.ashbyhq.com/DeepL", ["DE", "NL", "GB"], ["job"]),
    ("Synthesia", "https://jobs.ashbyhq.com/synthesia", ["GB"], ["job"]),
    ("Wayve", "https://jobs.ashbyhq.com/wayve", ["GB"], ["job"]),
    ("Spotify", "https://jobs.lever.co/spotify", ["SE"], ["job"]),
    ("Adyen", "https://job-boards.greenhouse.io/adyen", ["NL"], ["job"]),
    ("Celonis", "https://job-boards.greenhouse.io/celonis", ["DE"], ["job"]),
    ("GetYourGuide", "https://job-boards.greenhouse.io/getyourguide", ["DE", "CH"], ["job"]),
    ("Delivery Hero", "https://jobs.smartrecruiters.com/DeliveryHero", ["DE"], ["job"]),
    ("N26", "https://job-boards.greenhouse.io/n26", ["DE"], ["job"]),
    ("Philips", "https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers", ["NL"], ["job"]),
    ("Wise", "https://job-boards.greenhouse.io/wise", ["GB"], ["job"]),
    ("Dataiku", "https://job-boards.greenhouse.io/dataiku", ["FR"], ["job"]),
    ("Bosch", "https://jobs.smartrecruiters.com/BoschGroup", ["DE"], ["job"]),
    ("Hugging Face", "https://apply.workable.com/huggingface/", ["FR"], ["job"]),
    ("Personio", "https://personio.jobs.personio.de", ["DE"], ["job"]),
    ("Aalto University", "https://aalto.wd3.myworkdayjobs.com/en-US/aalto", ["FI"], ["phd", "job"]),
    ("Uppsala University", "https://uu.varbi.com", ["SE"], ["phd", "job"]),
    ("Lund University", "https://lu.varbi.com", ["SE"], ["phd", "job"]),
    ("KTH Royal Institute of Technology", "https://kth.varbi.com", ["SE"], ["phd", "job"]),
    # Checked live on 2026-10-19 (each returned postings, except Luleå with none open that day).
    ("Stockholm University", "https://su.varbi.com", ["SE"], ["phd", "job"]),
    ("Karolinska Institutet", "https://ki.varbi.com", ["SE"], ["phd", "job"]),
    ("Umeå University", "https://umu.varbi.com", ["SE"], ["phd", "job"]),
    ("Karlstad University", "https://kau.varbi.com", ["SE"], ["phd", "job"]),
    ("Mid Sweden University", "https://miun.varbi.com", ["SE"], ["phd", "job"]),
    ("Halmstad University", "https://hh.varbi.com", ["SE"], ["phd", "job"]),
    ("Jönköping University", "https://ju.varbi.com", ["SE"], ["phd", "job"]),
    ("Luleå University of Technology", "https://ltu.varbi.com", ["SE"], ["phd", "job"]),
    ("Tampere University", "https://tuni.rekrytointi.com/paikat/?o=A_RSS&jgid=1", ["FI"],
     ["phd", "job"]),
]

BOARDS = [
    # provider, name, countries, kinds, config
    ("workinfinland", "Work in Finland (Business Finland)", ["FI"], ["job", "phd"], {}),
    ("thehub", "The Hub: Finland", ["FI"], ["job"], {"countryCode": "FI"}),
    ("thehub", "The Hub: Nordics & EU", ["DK", "SE", "NO", "FI"], ["job"], {"countryCode": "EU"}),
    ("platsbanken", "Platsbanken (Sweden)", ["SE"], ["job"], {}),
    ("arbeitsagentur", "Bundesagentur für Arbeit (Germany)", ["DE"], ["job"], {}),
    ("arbeitnow", "Arbeitnow (Germany & EU, English)", ["DE"], ["job"], {}),
    ("landingjobs", "Landing.jobs (Portugal & EU tech)", ["PT"], ["job"], {}),
    ("justjoin", "Just Join IT (Poland)", ["PL"], ["job"], {}),
    ("nofluffjobs", "No Fluff Jobs (Poland & CEE)", ["PL"], ["job"], {}),
    ("solidjobs", "SolidJobs IT (Poland)", ["PL"], ["job"], {"division": "it"}),
    ("remotive", "Remotive (remote)", [], ["job"], {}),
    ("remoteok", "Remote OK (remote)", [], ["job"], {}),
    ("himalayas", "Himalayas (remote)", [], ["job"], {}),
    ("jobicy", "Jobicy (remote)", [], ["job"], {}),
    ("workingnomads", "Working Nomads (remote)", [], ["job"], {}),
    ("weworkremotely", "We Work Remotely (remote)", [], ["job"], {}),
    ("4dayweek", "4 Day Week", [], ["job"], {}),
]

MANUAL = [
    # name, url, reason
    ("Duunitori (Finland)", "https://duunitori.fi",
     "Blocks automated access (HTTP 403 even for robots.txt). Search and apply on the site."),
    ("Työmarkkinatori (Finland)", "https://tyomarkkinatori.fi",
     "Its job APIs need organization credentials (business ID); robots.txt disallows /api/. Many "
     "of its English-friendly jobs are in Work in Finland, which NexScout reads."),
    ("EURAXESS (EU research jobs)", "https://euraxess.ec.europa.eu/jobs/search",
     "robots.txt disallows /jobs/* and there's no public API. Search there yourself."),
    ("EURES (EU job mobility portal)", "https://europa.eu/eures/portal/jv-se/home",
     "No public API. Search there yourself."),
    ("Academic Positions", "https://academicpositions.com",
     "Blocks automated access (HTTP 403)."),
    ("AcademicTransfer (Netherlands)", "https://www.academictransfer.com",
     "Its API requires credentials and its robots.txt disallows it."),
    ("FindAPhD", "https://www.findaphd.com",
     "robots.txt disallows its search pages and it blocks automated access (HTTP 403)."),
    ("LinkedIn Jobs", "https://www.linkedin.com/jobs", "LinkedIn's terms prohibit automation."),
    ("Indeed", "https://www.indeed.com", "Indeed's terms prohibit automated access."),
    ("Glassdoor", "https://www.glassdoor.com", "Glassdoor's terms prohibit automated access."),
]


def key_for(provider: str, name: str, cfg: dict[str, object]) -> str:
    ident = cfg.get("slug") or cfg.get("host") or cfg.get("tenant") or cfg.get("countryCode") \
        or cfg.get("division") or cfg.get("collection") or name
    ident = re.sub(r"[^a-z0-9.-]+", "-", str(ident).lower()).strip("-")
    return f"{provider}:{ident}"[:100]


def _discover(rows: list[dict[str, object]]) -> dict[str, tuple[str, dict[str, object]]]:
    """Live: find the ATS board behind a branded careers page (only with --discover)."""
    if "--discover" not in sys.argv:
        return {}
    import asyncio

    async def run() -> dict[str, tuple[str, dict[str, object]]]:
        out: dict[str, tuple[str, dict[str, object]]] = {}
        for e in rows:
            url = str(e.get("careers_url") or "")
            if not url.startswith("https://"):
                continue
            try:
                pid, cfg, n = await probe(url, str(e.get("name", "")))
            except Exception as exc:  # noqa: BLE001 - report and move on
                print(f"  -- {e.get('name')}: {str(exc)[:80]}")
                continue
            if n and pid not in ("jsonld", "feed"):
                out[str(e.get("name", ""))] = (pid, cfg)
                print(f"  OK {e.get('name')}: {pid} {cfg} ({n} postings)")
        return out

    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def _verify(entries: dict[str, dict[str, object]]) -> dict[str, str]:
    """Live (only with --verify): read every entry once; boards that no longer exist (HTTP 404,
    usually a company that moved to another job system) are dropped with a dated reason.
    Other failures (timeouts, 5xx) are printed and kept: they're usually temporary."""
    if "--verify" not in sys.argv:
        return {}
    import asyncio
    from datetime import date

    from nexscout.integrations.sources.core import Entry, Http, SourceError

    async def run() -> dict[str, str]:
        gone: dict[str, str] = {}
        sem = asyncio.Semaphore(6)

        async def one(key: str, e: dict[str, object]) -> None:
            entry = Entry(key=key, provider=str(e["provider"]), name=str(e["name"]),
                          url=str(e["url"]), config=dict(e["config"]))  # type: ignore[arg-type]
            async with sem:
                try:
                    jobs = await PROVIDERS[entry.provider].fetch(Http(), entry)
                    print(f"  ok   {key}: {len(jobs)}")
                except SourceError as exc:
                    print(f"  FAIL {key}: {exc}")
                    if "doesn't exist" in str(exc):
                        gone[key] = (f"The board wasn't found when checked on {date.today()} "
                                     "(the company may have moved to another job system).")
                except Exception as exc:  # noqa: BLE001 - report and keep
                    print(f"  ERR  {key}: {type(exc).__name__}: {str(exc)[:80]}")

        await asyncio.gather(*(one(k, e) for k, e in entries.items()))
        return gone

    loop = asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(run())
    finally:
        loop.close()


def main(upstream: Path) -> None:
    data = yaml.safe_load((upstream / "templates/portals.example.yml").read_text(encoding="utf-8"))
    entries: dict[str, dict[str, object]] = {}
    unsupported: list[dict[str, str]] = []

    by_identity: dict[tuple[str, str, str], str] = {}

    def add(name: str, provider: str, url: str, cfg: dict[str, object], countries: list[str],
            kinds: list[str], category: str, origin: str) -> None:
        key = key_for(provider, name, cfg)
        # One entry per board actually fetched: a fixed board (Just Join IT, No Fluff Jobs...)
        # is the same feed whatever URL lists it; the others are told apart by config or URL.
        fixed = bool(getattr(PROVIDERS[provider], "fixed", ()))
        ident = (provider, repr(sorted(cfg.items())), "" if fixed or cfg else url.rstrip("/"))
        if key in entries or ident in by_identity:
            same = entries[by_identity.get(ident, key)]
            same["countries"] = sorted({*same["countries"], *countries})  # type: ignore[misc]
            same["kinds"] = sorted({*same["kinds"], *kinds})  # type: ignore[misc]
            return
        by_identity[ident] = key
        entries[key] = {"key": key, "provider": provider, "name": name, "url": url,
                        "config": cfg, "countries": countries, "kinds": kinds,
                        "category": category, "origin": origin}

    discovered = _discover([e for e in data.get("tracked_companies") or []
                            if not (detect_provider(str(e.get("api") or e.get("careers_url") or ""))
                                    or detect_provider(str(e.get("careers_url") or "")))])
    for e in data.get("tracked_companies") or []:
        name, url = str(e.get("name", "")).strip(), str(e.get("careers_url") or "")
        found = (detect_provider(str(e.get("api") or url)) or detect_provider(url)
                 or discovered.get(name))
        if found is None:
            unsupported.append({"name": name, "url": url, "reason": (
                "Listed for web search only upstream; no public board API found."
                if e.get("scan_method") == "websearch" else
                f"Provider '{e.get('provider') or 'unknown'}' isn't ported to NexScout yet.")})
            continue
        pid, cfg = found
        add(name, pid, url, cfg, [], ["job"], "company", "career-ops")
    for e in data.get("job_boards") or []:
        name, pid = str(e.get("name", "")).strip(), str(e.get("provider") or "")
        if pid not in PROVIDERS:
            unsupported.append({"name": name, "url": str(e.get("careers_url") or ""),
                                "reason": f"Board provider '{pid}' isn't ported to NexScout yet."})
            continue
        cfg = dict(e.get(pid) or {}) if isinstance(e.get(pid), dict) else {}
        if pid == "getro" and e.get("getro_collection"):
            cfg["collection"] = str(e["getro_collection"])
        if pid == "solidjobs" and e.get("careers_url"):
            m = re.search(r"/offers/([^/?]+)", str(e["careers_url"]))
            cfg["division"] = m.group(1) if m else "it"
        add(name, pid, str(e.get("careers_url") or ""), cfg, [], ["job"], "board", "career-ops")
    for name, url, countries, kinds in EU_ADDITIONS:
        found = detect_provider(url)
        assert found, url
        pid, cfg = found
        cat = "academic" if "phd" in kinds else "company"
        add(name, pid, url, cfg, countries, kinds, cat, "nexscout")
    for pid, name, countries, kinds, cfg in BOARDS:
        add(name, pid, "", cfg, countries, kinds, "board", "nexscout")
    for key, why in _verify(entries).items():
        e = entries.pop(key)
        unsupported.append({"name": str(e["name"]), "url": str(e["url"]), "reason": why})
    doc = {
        "upstream": {"project": "career-ops (MIT)", "url": "https://github.com/career-ops-hq/career-ops",
                     "commit": UPSTREAM_SHA},
        "entries": sorted(entries.values(), key=lambda x: (str(x["category"]), str(x["name"]).lower())),
        "manual_only": [{"name": n, "url": u, "reason": r} for n, u, r in MANUAL],
        "unsupported": sorted(unsupported, key=lambda x: x["name"].lower()),
    }
    OUT.write_text("# Generated by scripts/build_catalog.py. Edit that script, not this file.\n"
                   + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100),
                   encoding="utf-8")
    print(f"{len(entries)} entries, {len(unsupported)} unsupported, {len(MANUAL)} manual -> {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
