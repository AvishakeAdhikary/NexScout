"""M15: every source provider against a real (recorded, trimmed) response, plus URL detection.

Fixtures come from scripts/record_source_fixtures.py (public job-board data). A provider that
stops parsing a real response shape fails here without touching the network.
"""

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from nexscout.domain.opportunities import NormalizedOpportunity
from nexscout.integrations.sources.core import Entry, Http, SourceError, normalize_job
from nexscout.integrations.sources.providers import PROVIDERS, catalog, detect_provider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sources"
RECORDED = sorted(p.stem for p in FIXTURES.glob("*.json"))


class ReplayFetcher:
    """Answers each request with the recorded response for the same method and URL."""

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def request(
        self, method: str, url: str, **_: Any
    ) -> tuple[int, dict[str, str], bytes, str]:
        key = f"{method} {url}"
        self.calls.append(key)
        if key not in self.responses:
            return 200, {}, b"[]" if "json" in url or "api" in url else b"<rss></rss>", url
        r = self.responses[key]
        body = json.dumps(r["body"]) if r["kind"] == "json" else str(r["body"])
        return int(r["status"]), {}, body.encode(), url


def _run(pid: str) -> tuple[list[Any], Entry, ReplayFetcher]:
    data = json.loads((FIXTURES / f"{pid}.json").read_text(encoding="utf-8"))
    e = data["entry"]
    entry = Entry(key=f"{pid}:t", provider=pid, name=e["name"], url=e["url"], config=e["config"])
    fake = ReplayFetcher(data["responses"])
    jobs = asyncio.run(PROVIDERS[pid].fetch(Http(fake), entry))  # type: ignore[arg-type]
    return jobs, entry, fake


@pytest.mark.parametrize("pid", RECORDED)
def test_provider_parses_its_real_response(pid: str) -> None:
    jobs, entry, fake = _run(pid)
    assert fake.calls, "the provider made no request"
    assert jobs, f"{pid}: no postings parsed from the recorded response"
    for j in jobs:
        assert j.title.strip()
        assert urlsplit(j.url).scheme == "https"
        assert urlsplit(j.url).hostname
        norm = normalize_job(j, entry)
        assert isinstance(norm, NormalizedOpportunity)
        assert all(len(c) == 2 and c.isupper() for c in norm.country_codes)


def test_recordings_cover_every_provider_used_in_the_catalog() -> None:
    used = {e["provider"] for e in catalog()["entries"]}
    untested = used - set(RECORDED) - {"breezy", "pinpoint", "feed", "jsonld"}
    assert not untested, f"record fixtures for: {sorted(untested)}"


@pytest.mark.parametrize(
    ("url", "provider", "config"),
    [
        ("https://job-boards.greenhouse.io/anthropic", "greenhouse", {"slug": "anthropic"}),
        ("https://boards.eu.greenhouse.io/acme/jobs/1", "greenhouse", {"slug": "acme"}),
        ("https://jobs.eu.lever.co/acme", "lever", {"slug": "acme", "eu": True}),
        ("https://jobs.ashbyhq.com/elevenlabs", "ashby", {"slug": "elevenlabs"}),
        ("https://apply.workable.com/huggingface/", "workable", {"slug": "huggingface"}),
        ("https://jobs.smartrecruiters.com/BoschGroup", "smartrecruiters", {"slug": "BoschGroup"}),
        ("https://channable.recruitee.com/o/x", "recruitee", {"host": "channable.recruitee.com"}),
        ("https://acme.jobs.personio.de/", "personio", {"host": "acme.jobs.personio.de"}),
        ("https://acme.teamtailor.com/jobs", "teamtailor", {"host": "acme.teamtailor.com"}),
        ("https://acme.breezy.hr", "breezy", {"host": "acme.breezy.hr"}),
        ("https://ats.rippling.com/acme/jobs", "rippling", {"slug": "acme"}),
        ("https://uu.varbi.com/en/", "varbi", {"feed": "https://uu.varbi.com/en/what:rssfeed/"}),
        ("https://www.workinfinland.com/en/open-jobs", "workinfinland", {}),
        ("https://jobsinfinland.fi", "workinfinland", {}),
        (
            "https://example.org/careers/feed.rss",
            "feed",
            {"feed": "https://example.org/careers/feed.rss"},
        ),
        (  # Finnish universities' recruitment system: the feed is named in the query
            "https://tuni.rekrytointi.com/paikat/?o=A_RSS&jgid=1",
            "feed",
            {"feed": "https://tuni.rekrytointi.com/paikat/?o=A_RSS&jgid=1"},
        ),
    ],
)
def test_detects_provider_from_a_pasted_address(url: str, provider: str, config: dict) -> None:
    found = detect_provider(url)
    assert found is not None
    assert found[0] == provider
    assert found[1] == config


def test_workday_addresses() -> None:
    found = detect_provider("https://kone.wd3.myworkdayjobs.com/en-US/Careers")
    assert found == (
        "workday",
        {"origin": "https://kone.wd3.myworkdayjobs.com", "tenant": "kone", "site": "Careers"},
    )
    site = detect_provider("https://wd3.myworkdaysite.com/recruiting/acme/External")
    assert site is not None
    assert site[1]["recruiting"] is True


def test_unknown_addresses_are_not_guessed() -> None:
    assert detect_provider("https://www.example.com/about") is None
    assert detect_provider("") is None


def test_catalog_is_consistent() -> None:
    data = catalog()
    assert data["upstream"]["commit"]
    keys = [e["key"] for e in data["entries"]]
    assert len(keys) == len(set(keys)) >= 150
    fetched: set[tuple[str, str, str]] = set()
    for e in data["entries"]:
        assert e["provider"] in PROVIDERS, e
        assert all(len(c) == 2 for c in e["countries"]), e
        # Each board is fetched once: no two entries read the same thing.
        fixed = bool(getattr(PROVIDERS[e["provider"]], "fixed", ()))
        cfg = repr(sorted((e.get("config") or {}).items()))
        ident = (e["provider"], cfg, "" if fixed or e.get("config") else e["url"].rstrip("/"))
        assert ident not in fetched, e["key"]
        fetched.add(ident)
    reasons = {m["name"]: m["reason"] for m in data["manual_only"]}
    assert "robots.txt" in reasons["EURAXESS (EU research jobs)"]
    assert "403" in reasons["Duunitori (Finland)"]
    assert all(u["reason"] for u in data["unsupported"])


def test_html_instead_of_a_feed_is_a_clear_error() -> None:
    class Html(ReplayFetcher):
        async def request(
            self, method: str, url: str, **_: Any
        ) -> tuple[int, dict[str, str], bytes, str]:
            return 200, {}, b"<!DOCTYPE html><html><body>Jobs</body></html>", url

    entry = Entry(
        key="feed:t",
        provider="feed",
        name="X",
        url="https://x.example/rss",
        config={"feed": "https://x.example/rss"},
    )
    with pytest.raises(SourceError, match="web page, not a feed"):
        asyncio.run(PROVIDERS["feed"].fetch(Http(Html({})), entry))  # type: ignore[arg-type]
