"""Record one real, trimmed response per source provider for offline tests.

    uv run --project backend python scripts/record_source_fixtures.py

Each provider is run once against a real public board; every HTTP response it receives is saved
(JSON lists trimmed to 3 items, feeds to 3 entries) under backend/tests/fixtures/sources/, keyed
by URL. Tests replay these through a fake fetcher, so they exercise real response shapes without
the network. Public job-board data only.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from nexscout.infrastructure.fetch import SafeFetcher  # noqa: E402
from nexscout.integrations.sources.core import USER_AGENT, Entry, Http  # noqa: E402
from nexscout.integrations.sources.providers import PROVIDERS, detect_provider  # noqa: E402

OUT = ROOT / "backend/tests/fixtures/sources"
SAMPLES = [
    ("greenhouse", "Anthropic", "https://job-boards.greenhouse.io/anthropic", {}),
    ("lever", "Palantir", "https://jobs.lever.co/palantir", {}),
    ("ashby", "ElevenLabs", "https://jobs.ashbyhq.com/elevenlabs", {}),
    ("workable", "Hugging Face", "https://apply.workable.com/huggingface/", {}),
    ("smartrecruiters", "Bosch", "https://jobs.smartrecruiters.com/BoschGroup", {"max_pages": 1}),
    ("recruitee", "Channable", "https://channable.recruitee.com", {}),
    ("workday", "KONE", "https://kone.wd3.myworkdayjobs.com/en-US/Careers", {"max_pages": 1}),
    ("personio", "Personio", "https://personio.jobs.personio.de", {}),
    ("teamtailor", "Polestar", "https://polestar.teamtailor.com", {}),
    ("rippling", "Rippling", "https://ats.rippling.com/rippling/jobs", {"max_pages": 1}),
    ("varbi", "Uppsala University", "https://uu.varbi.com", {}),
    ("workinfinland", "Work in Finland", "", {}),
    ("arbeitnow", "Arbeitnow", "", {"max_pages": 1}),
    ("thehub", "The Hub", "", {"max_pages": 1, "countryCode": "FI"}),
    ("landingjobs", "Landing.jobs", "", {"max_pages": 1}),
    ("justjoin", "Just Join IT", "", {"max_pages": 1}),
    ("solidjobs", "SolidJobs", "", {"division": "it"}),
    ("platsbanken", "Platsbanken", "", {"keywords": ["machine learning"], "max_pages": 1}),
    ("arbeitsagentur", "Arbeitsagentur", "", {"keywords": ["Machine Learning"]}),
    ("remotive", "Remotive", "", {}),
    ("remoteok", "Remote OK", "", {}),
    ("workingnomads", "Working Nomads", "", {}),
    ("jobicy", "Jobicy", "", {}),
    ("himalayas", "Himalayas", "", {"max_pages": 1}),
    ("4dayweek", "4 Day Week", "", {"max_pages": 1}),
    ("weworkremotely", "We Work Remotely", "", {}),
    ("nofluffjobs", "No Fluff Jobs", "", {"keywords": ["machine learning"]}),
    ("getro", "b2venture", "https://jobs.b2venture.vc/jobs", {"collection": "4283", "max_pages": 1}),
]


def trim_json(data: object) -> object:
    if isinstance(data, list):
        # Keep usable items (some boards list paywalled "locked" postings first).
        usable = [x for x in data if not (isinstance(x, dict) and x.get("locked"))]
        return [trim_json(x) for x in (usable or data)[:3]]
    if isinstance(data, dict):
        return {k: trim_json(v) if k not in ("categories", "cities", "facetten") else v
                for k, v in data.items()}
    return data


def trim_xml(text: str) -> str:
    for tag in ("item", "position", "entry"):
        blocks = re.findall(rf"<{tag}\b.*?</{tag}>", text, re.S)
        if len(blocks) > 3:
            first = text.find(blocks[0])
            last = text.find(blocks[-1]) + len(blocks[-1])
            text = text[:first] + "".join(blocks[:3]) + text[last:]
    return text


class Recorder(SafeFetcher):
    def __init__(self) -> None:
        super().__init__(user_agent=USER_AGENT, respect_robots=False, max_bytes=15 * 1024 * 1024)
        self.seen: dict[str, dict[str, object]] = {}

    async def request(self, method, url, *, content=None, headers=None, check_robots=None):  # type: ignore[override]
        status, hdrs, body, final = await super().request(
            method, url, content=content, headers=headers, check_robots=check_robots)
        text = body.decode("utf-8", errors="replace")
        try:
            saved: object = trim_json(json.loads(text))
            kind = "json"
        except ValueError:
            saved, kind = trim_xml(text)[:200_000], "text"
        self.seen[f"{method} {url}"] = {"status": status, "kind": kind, "body": saved}
        return status, hdrs, body, final


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for pid, name, url, cfg in SAMPLES:
        if only and pid not in only:
            continue
        rec = Recorder()
        detected = (detect_provider(url) or (pid, {}))[1] if url else {}
        entry = Entry(key=f"{pid}:fixture", provider=pid, name=name, url=url,
                      config={**detected, **cfg})
        try:
            jobs = await PROVIDERS[pid].fetch(Http(rec), entry)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {pid}: {exc}")
            continue
        payload = {"provider": pid, "entry": {"name": name, "url": url, "config": entry.config},
                   "live_jobs": len(jobs), "responses": rec.seen}
        (OUT / f"{pid}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
        print(f"OK   {pid}: {len(jobs)} live jobs, {len(rec.seen)} responses")


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
