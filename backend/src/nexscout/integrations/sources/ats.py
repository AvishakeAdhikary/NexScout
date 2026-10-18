"""Applicant-tracking systems' public job-board APIs (one company per source entry).

Ported from career-ops providers/*.mjs (MIT; endpoints, host allow-lists and field mappings) at the
commit pinned in THIRD_PARTY_NOTICES.md. Every request goes to the vendor's documented public
board endpoint, never to a login-protected page.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from nexscout.integrations.sources.core import (
    MAX_PAGES,
    Entry,
    Http,
    Job,
    SourceError,
    first,
    html_to_text,
    https_url,
    iso_date,
    join_loc,
    slug_from,
)

TERMS_ATS = (
    "The employer's public job board on {vendor}, read through the vendor's public "
    "board API (no login). Apply on the employer's page."
)


def _require(slug: str | None, what: str) -> str:
    if not slug:
        raise SourceError(f"Couldn't find the {what} in this address.")
    return slug


class Greenhouse:
    id, label, category = "greenhouse", "Greenhouse", "ats"
    terms = TERMS_ATS.format(vendor="Greenhouse")

    def detect(self, url: str) -> dict[str, Any] | None:
        slug = slug_from(url, r"(?:job-boards(?:\.eu)?|boards(?:\.eu)?)\.greenhouse\.io/([^/?#]+)")
        slug = slug or slug_from(url, r"boards-api\.greenhouse\.io/v1/boards/([^/?#]+)")
        slug = slug or slug_from(url, r"greenhouse\.io/embed/job_board\?for=([^&#]+)")
        return {"slug": slug} if slug and slug != "embed" else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        slug = _require(
            entry.config.get("slug") or (self.detect(entry.api or entry.url) or {}).get("slug"),
            "Greenhouse board name",
        )
        data = await http.json(
            f"https://boards-api.greenhouse.io/v1/boards/{quote(slug)}/jobs?content=true"
        )
        out = []
        for j in data.get("jobs") or []:
            url = https_url(j.get("absolute_url"))
            if not url:
                continue
            offices = ", ".join(o.get("name", "") for o in j.get("offices") or [] if o.get("name"))
            out.append(
                Job(
                    title=first(j.get("title")),
                    url=url,
                    company=entry.name,
                    location=join_loc((j.get("location") or {}).get("name"), offices),
                    description=html_to_text(j.get("content")),
                    posted_at=iso_date(j.get("first_published") or j.get("updated_at")),
                    external_id=str(j.get("id")) if j.get("id") is not None else None,
                    requisition_id=first(j.get("requisition_id")) or None,
                )
            )
        return out


class Lever:
    id, label, category = "lever", "Lever", "ats"
    terms = TERMS_ATS.format(vendor="Lever")

    def detect(self, url: str) -> dict[str, Any] | None:
        m = re.search(r"jobs\.(eu\.)?lever\.co/([^/?#]+)", url or "", re.I)
        m = m or re.search(r"api\.(eu\.)?lever\.co/v0/postings/([^/?#]+)", url or "", re.I)
        return {"slug": m.group(2), "eu": bool(m.group(1))} if m else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        cfg = entry.config or self.detect(entry.api or entry.url) or {}
        slug = _require(cfg.get("slug"), "Lever company name")
        host = "api.eu.lever.co" if cfg.get("eu") else "api.lever.co"
        data = await http.json(f"https://{host}/v0/postings/{quote(slug)}?mode=json")
        out = []
        for j in data if isinstance(data, list) else []:
            url = https_url(j.get("hostedUrl"))
            if not url:
                continue
            cats = j.get("categories") or {}
            locs = [cats.get("location"), *(cats.get("allLocations") or [])]
            lists = "\n".join(
                f"{x.get('text', '')}\n{html_to_text(x.get('content'))}"
                for x in j.get("lists") or []
            )
            out.append(
                Job(
                    title=first(j.get("text")),
                    url=url,
                    company=entry.name,
                    location=join_loc(*locs),
                    description="\n\n".join(
                        p
                        for p in (
                            first(j.get("descriptionPlain")) or html_to_text(j.get("description")),
                            lists,
                            first(j.get("additionalPlain")),
                        )
                        if p
                    ),
                    posted_at=iso_date(j.get("createdAt")),
                    external_id=first(j.get("id")) or None,
                    remote=(j.get("workplaceType") == "remote") or None,
                    employment_type=first(cats.get("commitment")) or None,
                )
            )
        return out


_ASHBY_INTERVALS = {
    "1 HOUR": 2080,
    "1 DAY": 260,
    "1 WEEK": 52,
    "2 WEEK": 26,
    "0.5 MONTH": 24,
    "1 MONTH": 12,
    "2 MONTH": 6,
    "3 MONTH": 4,
    "6 MONTH": 2,
    "1 YEAR": 1,
}


def _ashby_salary(j: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    comp = j.get("compensation") or {}
    comps = [
        c
        for t in comp.get("compensationTiers") or []
        for c in t.get("components") or []
        if str(c.get("compensationType", "")).lower() == "salary"
        and c.get("interval") in _ASHBY_INTERVALS
        and (c.get("minValue") is not None or c.get("maxValue") is not None)
    ]
    if not comps:
        return None, None, None
    c = comps[0]
    mult = _ASHBY_INTERVALS[c["interval"]]
    lo = c.get("minValue") if c.get("minValue") is not None else c.get("maxValue")
    hi = c.get("maxValue") if c.get("maxValue") is not None else c.get("minValue")
    try:
        lo_f, hi_f = float(lo) * mult, float(hi) * mult
    except (TypeError, ValueError):
        return None, None, None
    return min(lo_f, hi_f), max(lo_f, hi_f), (c.get("currencyCode") or "").upper() or None


class Ashby:
    id, label, category = "ashby", "Ashby", "ats"
    terms = TERMS_ATS.format(vendor="Ashby")

    def detect(self, url: str) -> dict[str, Any] | None:
        slug = slug_from(url, r"jobs\.ashbyhq\.com/([^/?#]+)")
        slug = slug or slug_from(url, r"api\.ashbyhq\.com/posting-api/job-board/([^/?#]+)")
        return {"slug": slug} if slug else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        slug = _require(
            entry.config.get("slug") or (self.detect(entry.api or entry.url) or {}).get("slug"),
            "Ashby board name",
        )
        data = await http.json(
            f"https://api.ashbyhq.com/posting-api/job-board/{quote(slug)}?includeCompensation=true"
        )
        out = []
        for j in data.get("jobs") or []:
            url = https_url(j.get("jobUrl"))
            if not url:
                continue
            pa = (j.get("address") or {}).get("postalAddress") or {}
            secondary = [s.get("location") for s in j.get("secondaryLocations") or []]
            lo, hi, cur = _ashby_salary(j)
            out.append(
                Job(
                    title=first(j.get("title")),
                    url=url,
                    company=entry.name,
                    location=join_loc(
                        j.get("location"),
                        pa.get("addressLocality"),
                        pa.get("addressCountry"),
                        *secondary,
                    ),
                    description=first(j.get("descriptionPlain"))
                    or html_to_text(j.get("descriptionHtml")),
                    posted_at=iso_date(j.get("publishedAt")),
                    external_id=first(j.get("id")) or None,
                    remote=bool(j.get("isRemote")) or None,
                    salary_min=lo,
                    salary_max=hi,
                    salary_currency=cur,
                    employment_type=first(j.get("employmentType")) or None,
                )
            )
        return out


class Workable:
    id, label, category = "workable", "Workable", "ats"
    terms = TERMS_ATS.format(vendor="Workable")

    def detect(self, url: str) -> dict[str, Any] | None:
        slug = slug_from(url, r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([^/?#]+)")
        slug = slug or slug_from(url, r"https?://([a-z0-9-]+)\.workable\.com")
        return {"slug": slug} if slug and slug not in ("api", "www") else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        slug = _require(
            entry.config.get("slug") or (self.detect(entry.api or entry.url) or {}).get("slug"),
            "Workable account name",
        )
        data = await http.json(
            f"https://apply.workable.com/api/v1/widget/accounts/{quote(slug)}?details=true",
            headers={"Referer": f"https://apply.workable.com/{slug}/"},
        )
        by_url: dict[str, Job] = {}
        for j in data.get("jobs") or []:
            url = https_url(j.get("shortlink")) or https_url(j.get("url"))
            title = first(j.get("title"))
            if not url or not title:
                continue
            loc = join_loc(j.get("city"), j.get("state"), j.get("country")) or (
                "Remote" if j.get("telecommuting") else ""
            )
            if url in by_url:
                if loc and loc not in by_url[url].location:
                    by_url[url].location = f"{by_url[url].location} · {loc}".strip(" ·")
                continue
            by_url[url] = Job(
                title=title,
                url=url,
                company=first(data.get("name"), entry.name),
                location=loc,
                description=html_to_text(j.get("description")),
                posted_at=iso_date(j.get("published_on") or j.get("created_at")),
                remote=bool(j.get("telecommuting")) or None,
                employment_type=first(j.get("employment_type")) or None,
            )
        return list(by_url.values())


class SmartRecruiters:
    id, label, category = "smartrecruiters", "SmartRecruiters", "ats"
    terms = TERMS_ATS.format(vendor="SmartRecruiters")

    def detect(self, url: str) -> dict[str, Any] | None:
        slug = slug_from(url, r"(?:careers|jobs)\.smartrecruiters\.com/([^/?#]+)")
        slug = slug or slug_from(url, r"api\.smartrecruiters\.com/v1/companies/([^/?#]+)")
        return {"slug": slug} if slug else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        slug = _require(
            entry.config.get("slug") or (self.detect(entry.api or entry.url) or {}).get("slug"),
            "SmartRecruiters company id",
        )
        out: list[Job] = []
        for page in range(_max_pages(entry)):
            data = await http.json(
                f"https://api.smartrecruiters.com/v1/companies/{quote(slug)}"
                f"/postings?limit=100&offset={page * 100}&status=PUBLIC"
            )
            items = data.get("content") or []
            for j in items:
                loc = j.get("location") or {}
                name = first(j.get("name"))
                slugified = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                url = f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}" + (
                    f"-{slugified}" if slugified else ""
                )
                out.append(
                    Job(
                        title=name,
                        url=url,
                        company=first((j.get("company") or {}).get("name"), entry.name),
                        location=join_loc(
                            loc.get("fullLocation")
                            or join_loc(loc.get("city"), loc.get("region"), loc.get("country")),
                            "Remote" if loc.get("remote") else "",
                        ),
                        country=(loc.get("country") or "").upper() or None,
                        posted_at=iso_date(j.get("releasedDate")),
                        external_id=str(j.get("id")) if j.get("id") else None,
                        requisition_id=first(j.get("refNumber")) or None,
                        remote=bool(loc.get("remote")) or None,
                        employment_type=first((j.get("typeOfEmployment") or {}).get("label"))
                        or None,
                    )
                )
            total = data.get("totalFound") or 0
            if not items or len(out) >= total:
                break
        return out


class Recruitee:
    id, label, category = "recruitee", "Recruitee", "ats"
    terms = TERMS_ATS.format(vendor="Recruitee")

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url).hostname or "").lower()
        return {"host": host} if host.endswith(".recruitee.com") else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        host = _require(
            entry.config.get("host") or (self.detect(entry.url) or {}).get("host"),
            "Recruitee address",
        )
        data = await http.json(f"https://{host}/api/offers/")
        out = []
        for o in data.get("offers") or []:
            url = https_url(o.get("careers_url")) or https_url(o.get("careers_apply_url"))
            if not url:
                continue
            locs = [
                x.get("name") or join_loc(x.get("city"), x.get("country"))
                for x in o.get("locations") or []
            ]
            out.append(
                Job(
                    title=first(o.get("title")),
                    url=url,
                    company=first(o.get("company_name"), entry.name),
                    location=join_loc(o.get("location"), *locs)
                    or join_loc(o.get("city"), o.get("country")),
                    country=(o.get("country_code") or "").upper() or None,
                    description=html_to_text(
                        f"{o.get('description', '')}\n{o.get('requirements', '')}"
                    ),
                    posted_at=iso_date(o.get("published_at") or o.get("created_at")),
                    external_id=str(o.get("id")) if o.get("id") else None,
                    remote=bool(o.get("remote")) or None,
                    employment_type=first(o.get("employment_type_code")) or None,
                )
            )
        return out


def _xml(text: str) -> ET.Element:
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype html") or head.startswith("<html"):
        raise SourceError("This address returns a web page, not a feed.")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise SourceError("The feed uses XML features NexScout doesn't read (DTD/entities).")
    try:
        return ET.fromstring(text)  # noqa: S314 - DTDs refused above, so no entity expansion
    except ET.ParseError as exc:
        raise SourceError("The feed isn't valid XML.") from exc


def _t(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    found = el.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


class Personio:
    id, label, category = "personio", "Personio", "ats"
    terms = TERMS_ATS.format(vendor="Personio")

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url).hostname or "").lower()
        return {"host": host} if re.search(r"\.jobs\.personio\.(de|com)$", host) else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        host = _require(
            entry.config.get("host") or (self.detect(entry.url) or {}).get("host"),
            "Personio address",
        )
        root = _xml(await http.text(f"https://{host}/xml", accept="application/xml"))
        out = []
        for p in root.iter("position"):
            pid = _t(p, "id")
            if not pid:
                continue
            offices = [
                _t(p, "office"),
                *[(o.text or "").strip() for o in p.iter("additionalOffice")],
            ]
            desc = " ".join(
                html_to_text(v.findtext("value") or "") for v in p.iter("jobDescription")
            )
            out.append(
                Job(
                    title=_t(p, "name"),
                    url=f"https://{host}/job/{pid}",
                    company=first(_t(p, "subcompany"), entry.name),
                    location=join_loc(*offices),
                    description=desc,
                    posted_at=iso_date(_t(p, "createdAt")),
                    external_id=pid,
                    employment_type=_t(p, "employmentType") or None,
                )
            )
        return out


def _rss_items(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("item")) or [e for e in root.iter() if e.tag.endswith("}entry")]


class Teamtailor:
    id, label, category = "teamtailor", "Teamtailor", "ats"
    terms = TERMS_ATS.format(vendor="Teamtailor")

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url).hostname or "").lower()
        return {"host": host} if host.endswith(".teamtailor.com") else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        host = _require(
            entry.config.get("host") or (self.detect(entry.url) or {}).get("host"),
            "Teamtailor address",
        )
        root = _xml(await http.text(f"https://{host}/jobs.rss", accept="application/rss+xml"))
        out = []
        for it in _rss_items(root):
            url = https_url(_t(it, "link"))
            if not url:
                continue
            locs = [
                (e.text or "").strip()
                for e in it.iter()
                if e.tag.endswith("}location")
                or e.tag.endswith("}city")
                or e.tag.endswith("}country")
            ]
            out.append(
                Job(
                    title=_t(it, "title"),
                    url=url,
                    company=entry.name,
                    location=join_loc(*locs),
                    description=html_to_text(_t(it, "description")),
                    posted_at=iso_date(_t(it, "pubDate")),
                    external_id=_t(it, "guid") or None,
                )
            )
        return out


class Breezy:
    id, label, category = "breezy", "Breezy HR", "ats"
    terms = TERMS_ATS.format(vendor="Breezy HR")

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url).hostname or "").lower()
        return {"host": host} if host.endswith(".breezy.hr") else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        host = _require(
            entry.config.get("host") or (self.detect(entry.url) or {}).get("host"), "Breezy address"
        )
        data = await http.json(f"https://{host}/json")
        out = []
        for j in data if isinstance(data, list) else []:
            url = https_url(j.get("url"))
            if not url or not j.get("name"):
                continue
            loc = j.get("location") or {}
            country = (loc.get("country") or {}) if isinstance(loc.get("country"), dict) else {}
            out.append(
                Job(
                    title=str(j["name"]),
                    url=url,
                    company=first((j.get("company") or {}).get("name"), entry.name),
                    location=join_loc(
                        loc.get("name") or join_loc(loc.get("city"), loc.get("state")),
                        country.get("name"),
                        "Remote" if loc.get("is_remote") else "",
                    ),
                    country=(country.get("id") or "").upper() or None,
                    posted_at=iso_date(j.get("published_date")),
                    external_id=first(j.get("id")) or None,
                    remote=bool(loc.get("is_remote")) or None,
                    employment_type=first((j.get("type") or {}).get("name")) or None,
                )
            )
        return out


class Pinpoint:
    id, label, category = "pinpoint", "Pinpoint", "ats"
    terms = TERMS_ATS.format(vendor="Pinpoint")

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url).hostname or "").lower()
        return {"host": host} if host.endswith(".pinpointhq.com") else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        host = _require(
            entry.config.get("host") or (self.detect(entry.url) or {}).get("host"),
            "Pinpoint address",
        )
        data = await http.json(f"https://{host}/postings.json")
        out = []
        for j in data.get("data") or []:
            url, title = https_url(j.get("url")), first(j.get("title"))
            if not url or not title:
                continue
            loc = j.get("location") or {}
            out.append(
                Job(
                    title=title,
                    url=url,
                    company=entry.name,
                    location=first(loc.get("name"))
                    or join_loc(loc.get("city"), loc.get("province")),
                    description=html_to_text(j.get("description")),
                    external_id=str(j.get("id")) if j.get("id") else None,
                    employment_type=first(j.get("employment_type_text")) or None,
                )
            )
        return out


class Rippling:
    id, label, category = "rippling", "Rippling", "ats"
    terms = TERMS_ATS.format(vendor="Rippling")

    def detect(self, url: str) -> dict[str, Any] | None:
        slug = slug_from(url, r"ats\.rippling\.com/(?:api/v2/board/)?([^/?#]+)")
        return {"slug": slug} if slug and slug != "api" else None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        slug = _require(
            entry.config.get("slug") or (self.detect(entry.url) or {}).get("slug"),
            "Rippling board name",
        )
        out: list[Job] = []
        for page in range(_max_pages(entry)):
            data = await http.json(
                f"https://ats.rippling.com/api/v2/board/{quote(slug)}/jobs?page={page}&pageSize=50"
            )
            items = data.get("items") or []
            for j in items:
                url = https_url(j.get("url"), {"ats.rippling.com"})
                if url and first(j.get("name")):
                    out.append(
                        Job(
                            title=first(j.get("name")),
                            url=url,
                            company=entry.name,
                            location=" · ".join(
                                x.get("name", "") for x in j.get("locations") or [] if x.get("name")
                            ),
                            external_id=first(j.get("id")) or None,
                        )
                    )
            if len(items) < 50:
                break
        return out


_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)\+?\s+days?\s+ago)", re.I)


def _workday_posted(label: Any) -> str | None:
    m = _POSTED.search(str(label or ""))
    if not m:
        return None
    days = (
        0
        if m.group(1).lower() == "today"
        else 1
        if m.group(1).lower() == "yesterday"
        else int(m.group(2))
    )
    return (datetime.now(UTC) - timedelta(days=days)).date().isoformat()


class Workday:
    id, label, category = "workday", "Workday", "ats"
    terms = TERMS_ATS.format(vendor="Workday")
    _CAREERS = re.compile(
        r"^https://([\w-]+)\.(wd[\w-]*)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
        r"([^/?#]+)"
    )
    _CXS = re.compile(
        r"^https://([\w-]+)\.(wd[\w-]*)\.myworkdayjobs\.com/wday/cxs/([\w-]+)/([^/?#]+)"
    )
    _SITE = re.compile(r"^https://([\w-]+)\.myworkdaysite\.com/recruiting/([\w-]+)/([^/?#]+)")

    def detect(self, url: str) -> dict[str, Any] | None:
        if m := self._CXS.match(url or ""):
            origin = f"https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com"
            return {"origin": origin, "tenant": m.group(3), "site": m.group(4)}
        if m := self._CAREERS.match(url or ""):
            origin = f"https://{m.group(1)}.{m.group(2)}.myworkdayjobs.com"
            return {"origin": origin, "tenant": m.group(1), "site": m.group(3)}
        if m := self._SITE.match(url or ""):
            return {
                "origin": f"https://{m.group(1)}.myworkdaysite.com",
                "tenant": m.group(2),
                "site": m.group(3),
                "recruiting": True,
            }
        return None

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        cfg = (
            entry.config
            if entry.config.get("tenant")
            else (self.detect(entry.api or entry.url) or {})
        )
        if not cfg.get("tenant"):
            raise SourceError("Couldn't find the Workday site in this address.")
        origin, tenant, site = cfg["origin"], cfg["tenant"], cfg["site"]
        api = f"{origin}/wday/cxs/{tenant}/{site}/jobs"
        job_base = (
            f"{origin}/recruiting/{tenant}/{site}"
            if cfg.get("recruiting")
            else (f"{origin}/{site}")
        )
        searches = (
            [str(entry.config["search"])]
            if entry.config.get("search")
            else [str(k) for k in (entry.config.get("keywords") or [])][:4] or [""]
        )
        out: list[Job] = []
        seen: set[str] = set()
        for search in searches:
            await self._search(http, api, job_base, search, entry, out, seen)
        return out

    async def _search(
        self,
        http: Http,
        api: str,
        job_base: str,
        search: str,
        entry: Entry,
        out: list[Job],
        seen: set[str],
    ) -> None:
        total = None
        found = 0
        for page in range(int(entry.config.get("max_pages") or 10)):
            data = await http.json(
                api,
                method="POST",
                body={"limit": 20, "offset": page * 20, "searchText": search, "appliedFacets": {}},
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            postings = data.get("jobPostings") or []
            total = data.get("total") if total is None else total
            found += len(postings)
            for j in postings:
                path = j.get("externalPath")
                if not path or not first(j.get("title")):
                    continue
                loc = first(j.get("locationsText"))
                if not loc and (m := re.search(r"/job/([^/]+)/", path)):
                    loc = m.group(1).replace("-", " ")
                req = [*path.rstrip("/").split("/")[-1].rsplit("_", 1), ""][1] or None
                if job_base + path in seen:
                    continue
                seen.add(job_base + path)
                out.append(
                    Job(
                        title=first(j.get("title")),
                        url=job_base + path,
                        company=entry.name,
                        location=loc,
                        posted_at=_workday_posted(j.get("postedOn")),
                        requisition_id=req,
                    )
                )
            if len(postings) < 20 or (total and found >= int(total)):
                break


PROVIDERS: dict[str, Any] = {
    p.id: p
    for p in (
        Greenhouse(),
        Lever(),
        Ashby(),
        Workable(),
        SmartRecruiters(),
        Recruitee(),
        Personio(),
        Teamtailor(),
        Breezy(),
        Pinpoint(),
        Rippling(),
        Workday(),
    )
}


def _max_pages(entry: Entry) -> int:
    try:
        return max(1, min(int(entry.config.get("max_pages") or MAX_PAGES), MAX_PAGES))
    except (TypeError, ValueError):
        return MAX_PAGES
