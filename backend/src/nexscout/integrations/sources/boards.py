"""Job boards with public APIs or feeds (many employers per source).

Ported from career-ops providers/*.mjs (MIT) at the commit pinned in THIRD_PARTY_NOTICES.md:
same public endpoints, paging and field mappings. Search-style boards use the case's keywords.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from nexscout.integrations.sources.ats import _rss_items, _t, _xml
from nexscout.integrations.sources.core import (
    Entry,
    Http,
    Job,
    SourceError,
    first,
    html_to_text,
    https_url,
    iso_date,
    join_loc,
)


def _pages(entry: Entry, default: int) -> int:
    try:
        return max(1, min(int(entry.config.get("max_pages") or default), 25))
    except (TypeError, ValueError):
        return default


def _keywords(entry: Entry) -> list[str]:
    kws = entry.config.get("keywords") or []
    return [str(k).strip() for k in kws if str(k).strip()][:8]


class _Board:
    id = label = ""
    category = "board"
    terms = "A public job board, read through its public API or feed. Apply on the posting's page."
    fixed: tuple[str, ...] = ()  # hosts that identify this board when pasted as a URL

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url or "").hostname or "").lower()
        return {} if any(host == h or host.endswith("." + h) for h in self.fixed) else None


class Arbeitnow(_Board):
    id, label, fixed = "arbeitnow", "Arbeitnow (Germany & EU)", ("arbeitnow.com",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out = []
        for page in range(1, _pages(entry, 5) + 1):
            data = await http.json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
            rows = data.get("data") or []
            for j in rows:
                url = https_url(j.get("url"), {"arbeitnow.com"})
                if url and first(j.get("title")):
                    out.append(
                        Job(
                            title=first(j.get("title")),
                            url=url,
                            company=first(j.get("company_name"), "Arbeitnow"),
                            location=join_loc(
                                j.get("location"), "Remote" if j.get("remote") else ""
                            ),
                            description=html_to_text(j.get("description")),
                            posted_at=iso_date(j.get("created_at")),
                            remote=bool(j.get("remote")) or None,
                            employment_type=", ".join(j.get("job_types") or []) or None,
                            external_id=first(j.get("slug")) or None,
                        )
                    )
            if not rows or not (data.get("links") or {}).get("next"):
                break
        return out


class TheHub(_Board):
    id, label, fixed = "thehub", "The Hub (Nordic startups)", ("thehub.io",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        country = str(entry.config.get("countryCode") or "EU")
        out: dict[str, Job] = {}
        for page in range(1, _pages(entry, 5) + 1):
            data = await http.json(
                "https://thehub.io/api/v2/jobsandfeatured?"
                + urlencode({"page": page, "countryCode": country})
            )
            jobs = data.get("jobs") or {}
            for j in jobs.get("docs") or []:
                jid = first(j.get("id"))
                if not jid or not first(j.get("title")):
                    continue
                loc = j.get("location") or {}
                url = f"https://thehub.io/jobs/{quote(jid)}"
                out.setdefault(
                    url,
                    Job(
                        title=first(j.get("title")),
                        url=url,
                        company=first((j.get("company") or {}).get("name"), "The Hub"),
                        location=join_loc(
                            loc.get("address") or join_loc(loc.get("locality"), loc.get("country")),
                            "Remote" if j.get("isRemote") else "",
                        ),
                        description=html_to_text(j.get("description")),
                        remote=bool(j.get("isRemote")) or None,
                        external_id=jid,
                    ),
                )
            if isinstance(jobs.get("pages"), int) and page >= jobs["pages"]:
                break
        return list(out.values())


class LandingJobs(_Board):
    id, label, fixed = "landingjobs", "Landing.jobs (Portugal & EU tech)", ("landing.jobs",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out = []
        for page in range(_pages(entry, 4)):
            data = await http.json(f"https://landing.jobs/api/v1/jobs?limit=50&offset={page * 50}")
            rows = data if isinstance(data, list) else []
            for j in rows:
                url = https_url(j.get("url"), {"landing.jobs"})
                if not url or not first(j.get("title")):
                    continue
                loc = (j.get("locations") or [{}])[0] or {}
                m = re.search(r"landing\.jobs/at/([^/]+)/", url)
                out.append(
                    Job(
                        title=first(j.get("title")),
                        url=url,
                        company=(m.group(1).replace("-", " ").title() if m else "Landing.jobs"),
                        location=join_loc(
                            loc.get("city"),
                            loc.get("country_code"),
                            "Remote" if j.get("remote") else "",
                        ),
                        country=(loc.get("country_code") or "").upper() or None,
                        description=html_to_text(
                            f"{j.get('role_description', '')}\n{j.get('main_requirements', '')}"
                        ),
                        posted_at=iso_date(j.get("published_at") or j.get("created_at")),
                        remote=bool(j.get("remote")) or None,
                        external_id=str(j.get("id")) if j.get("id") else None,
                    )
                )
            if len(rows) < 50:
                break
        return out


class JustJoin(_Board):
    id, label, fixed = "justjoin", "Just Join IT (Poland)", ("justjoin.it",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out = []
        for page in range(_pages(entry, 3)):
            params = {
                "from": page * 100,
                "itemsCount": 100,
                "orderBy": "descending",
                "sortBy": "publishedAt",
                "currency": "pln",
                "keywordType": "any",
            }
            data = await http.json(
                "https://justjoin.it/api/candidate-api/offers?" + urlencode(params)
            )
            rows = data.get("data") or []
            for o in rows:
                slug, title = first(o.get("slug")), first(o.get("title"))
                if slug and title:
                    cities = [loc.get("city") for loc in o.get("locations") or []]
                    out.append(
                        Job(
                            title=title,
                            url=f"https://justjoin.it/job-offer/{slug}",
                            company=first(o.get("companyName")),
                            location=join_loc(
                                o.get("city"),
                                *cities,
                                "Poland",
                                "Remote" if o.get("workplaceType") == "remote" else "",
                            ),
                            posted_at=iso_date(o.get("publishedAt")),
                            external_id=slug,
                            remote=(o.get("workplaceType") == "remote") or None,
                        )
                    )
            if len(rows) < 100:
                break
        return out


class SolidJobs(_Board):
    id, label, fixed = "solidjobs", "SolidJobs (Poland)", ("solid.jobs",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        division = str(entry.config.get("division") or "it")
        data = await http.json(
            f"https://solid.jobs/public-api/offers/{quote(division)}?campaign=nexscout"
        )
        out = []
        for j in data.get("jobs") or []:
            url = https_url(j.get("url"))
            if url:
                locs = j.get("locations")
                out.append(
                    Job(
                        title=first(j.get("title")),
                        url=url,
                        company=first(j.get("company"), entry.name),
                        location=", ".join(locs) if isinstance(locs, list) else first(locs),
                    )
                )
        return out


class Platsbanken(_Board):
    id, label = "platsbanken", "Platsbanken (Sweden, Arbetsförmedlingen)"
    fixed = ("arbetsformedlingen.se", "jobsearch.api.jobtechdev.se")
    terms = (
        "Sweden's public employment service, through its open JobTech JobSearch API. "
        "Apply on the posting's page."
    )

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out: dict[str, Job] = {}
        for kw in _keywords(entry) or ["machine learning"]:
            for page in range(_pages(entry, 2)):
                data = await http.json(
                    "https://jobsearch.api.jobtechdev.se/search?"
                    + urlencode({"q": kw, "limit": 100, "offset": page * 100})
                )
                hits = data.get("hits") or []
                for r in hits:
                    rid, title = first(str(r.get("id") or "")), first(r.get("headline"))
                    if not rid or not title:
                        continue
                    addr = r.get("workplace_address") or {}
                    url = f"https://arbetsformedlingen.se/platsbanken/annonser/{quote(rid)}"
                    out.setdefault(
                        url,
                        Job(
                            title=title,
                            url=url,
                            company=first((r.get("employer") or {}).get("name")),
                            location=join_loc(
                                addr.get("city") or addr.get("municipality"),
                                addr.get("region"),
                                addr.get("country") or "Sweden",
                            ),
                            country="SE",
                            description=first((r.get("description") or {}).get("text")),
                            posted_at=iso_date(r.get("publication_date")),
                            closes_at=iso_date(r.get("application_deadline")),
                            external_id=rid,
                        ),
                    )
                if len(hits) < 100:
                    break
        return list(out.values())


class Arbeitsagentur(_Board):
    id, label = "arbeitsagentur", "Bundesagentur für Arbeit (Germany)"
    fixed = ("arbeitsagentur.de",)
    terms = (
        "Germany's Federal Employment Agency job search, through the public client key its "
        "own website uses. Apply on the posting's page."
    )

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out: dict[str, Job] = {}
        for kw in _keywords(entry) or ["Machine Learning"]:
            params = {
                "was": kw,
                "size": 100,
                "page": 1,
                "angebotsart": 1,
                "veroeffentlichtseit": int(entry.config.get("days") or 30),
            }
            if entry.config.get("wo"):
                params["wo"] = entry.config["wo"]
            data = await http.json(
                "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs?"
                + urlencode(params),
                headers={"X-API-Key": "jobboerse-jobsuche"},
            )
            for j in data.get("ergebnisliste") or data.get("stellenangebote") or []:
                ref, title = (
                    first(j.get("referenznummer")),
                    first(j.get("stellenangebotsTitel") or j.get("titel")),
                )
                if not ref or not title:
                    continue
                locs = j.get("stellenlokationen") or [j.get("arbeitsort") or {}]
                loc = "; ".join(
                    join_loc(
                        (x.get("adresse") or x).get("ort"), (x.get("adresse") or x).get("region")
                    )
                    for x in locs
                    if x
                )
                url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{quote(ref)}"
                out.setdefault(
                    url,
                    Job(
                        title=title,
                        url=url,
                        company=first(j.get("firma")),
                        location=join_loc(loc, "Germany"),
                        country="DE",
                        posted_at=iso_date(
                            j.get("datumErsteVeroeffentlichung")
                            or j.get("aktuelleVeroeffentlichungsdatum")
                        ),
                        external_id=ref,
                    ),
                )
        return list(out.values())


class _SimpleJsonBoard(_Board):
    feed = ""
    rows_key: str | None = "jobs"
    title_key = "title"
    company_key = "company_name"
    location_key = "location"
    date_key = "publication_date"
    desc_key = "description"

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        data = await http.json(self.feed)
        rows = data.get(self.rows_key) if self.rows_key and isinstance(data, dict) else data
        out = []
        for j in rows if isinstance(rows, list) else []:
            if not isinstance(j, dict):
                continue
            url, title = https_url(j.get("url")), first(j.get(self.title_key))
            if url and title:
                out.append(
                    Job(
                        title=title,
                        url=url,
                        company=first(j.get(self.company_key), self.label),
                        location=first(j.get(self.location_key)) or "Remote",
                        description=html_to_text(j.get(self.desc_key)),
                        posted_at=iso_date(j.get(self.date_key)),
                        remote=True,
                        external_id=str(j.get("id")) if j.get("id") else None,
                    )
                )
        return out


class Remotive(_SimpleJsonBoard):
    id, label, fixed = "remotive", "Remotive (remote)", ("remotive.com",)
    feed = "https://remotive.com/api/remote-jobs"
    location_key = "candidate_required_location"


class RemoteOK(_SimpleJsonBoard):
    id, label, fixed = "remoteok", "Remote OK (remote)", ("remoteok.com",)
    feed, rows_key, title_key, company_key, date_key = (
        "https://remoteok.com/api",
        None,
        "position",
        "company",
        "date",
    )


class WorkingNomads(_SimpleJsonBoard):
    id, label, fixed = "workingnomads", "Working Nomads (remote)", ("workingnomads.com",)
    feed, rows_key, date_key = "https://www.workingnomads.com/api/exposed_jobs/", None, "pub_date"


class Jobicy(_SimpleJsonBoard):
    id, label, fixed = "jobicy", "Jobicy (remote)", ("jobicy.com",)
    feed, title_key, company_key, location_key, date_key, desc_key = (
        "https://jobicy.com/api/v2/remote-jobs?count=50",
        "jobTitle",
        "companyName",
        "jobGeo",
        "pubDate",
        "jobDescription",
    )


class Himalayas(_Board):
    id, label, fixed = "himalayas", "Himalayas (remote)", ("himalayas.app",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out = []
        for page in range(_pages(entry, 5)):
            data = await http.json(f"https://himalayas.app/jobs/api?limit=20&offset={page * 20}")
            rows = data.get("jobs") or []
            for j in rows:
                url = https_url(j.get("applicationLink")) or https_url(j.get("guid"))
                if url and first(j.get("title")):
                    out.append(
                        Job(
                            title=first(j.get("title")),
                            url=url,
                            company=first(j.get("companyName")),
                            location=", ".join(j.get("locationRestrictions") or [])
                            or "Remote (worldwide)",
                            description=html_to_text(j.get("description")),
                            posted_at=iso_date(j.get("pubDate")),
                            remote=True,
                        )
                    )
            if len(rows) < 20:
                break
        return out


class FourDayWeek(_Board):
    id, label, fixed = "4dayweek", "4 Day Week", ("4dayweek.io",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out = []
        for page in range(1, _pages(entry, 4) + 1):
            data = await http.json(f"https://4dayweek.io/api/jobs?page={page}")
            rows = data.get("jobs") or []
            for j in rows:
                slug = first(j.get("slug"))
                if not slug or not first(j.get("title")):
                    continue
                loc = (j.get("locations") or [{}])[0] or {}
                remote = j.get("work_arrangement") == "remote"
                out.append(
                    Job(
                        title=first(j.get("title")),
                        url=f"https://4dayweek.io/job/{quote(slug)}",
                        company=first(j.get("company_name"), (j.get("company") or {}).get("name")),
                        location=join_loc(
                            loc.get("city"), loc.get("country"), "Remote" if remote else ""
                        ),
                        posted_at=iso_date(j.get("posted")),
                        remote=remote or None,
                    )
                )
            if len(rows) < 20:
                break
        return out


class WeWorkRemotely(_Board):
    id, label, fixed = "weworkremotely", "We Work Remotely", ("weworkremotely.com",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        root = _xml(
            await http.text(
                "https://weworkremotely.com/remote-jobs.rss", accept="application/rss+xml"
            )
        )
        out = []
        for it in _rss_items(root):
            url, raw = https_url(_t(it, "link")), _t(it, "title")
            if not url or not raw:
                continue
            company, _, title = raw.partition(":")
            out.append(
                Job(
                    title=(title or raw).strip(),
                    url=url,
                    company=company.strip() if title else "We Work Remotely",
                    location=_t(it, "region") or "Remote",
                    description=html_to_text(_t(it, "description")),
                    posted_at=iso_date(_t(it, "pubDate")),
                    remote=True,
                )
            )
        return out


class NoFluffJobs(_Board):
    id, label, fixed = "nofluffjobs", "No Fluff Jobs (Poland & CEE)", ("nofluffjobs.com",)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        out: dict[str, Job] = {}
        for kw in _keywords(entry) or ["machine learning"]:
            data = await http.json(
                "https://nofluffjobs.com/api/search/posting?"
                + urlencode(
                    {
                        "sort": "newest",
                        "pageTo": 1,
                        "pageSize": 100,
                        "salaryCurrency": "PLN",
                        "salaryPeriod": "month",
                        "region": "pl",
                        "language": "en-GB",
                    }
                ),
                method="POST",
                body={
                    "rawSearch": kw,
                    "url": {"searchParam": kw},
                    "criteria": "",
                    "pageSize": 100,
                    "withSalaryMatch": True,
                },
            )
            for p in data.get("postings") or []:
                slug = first(p.get("url"))
                if not slug or not first(p.get("title")):
                    continue
                places = [
                    x.get("city") or x.get("country", {}).get("name", "")
                    for x in ((p.get("location") or {}).get("places") or [])
                ]
                url = f"https://nofluffjobs.com/job/{quote(slug)}"
                out.setdefault(
                    url,
                    Job(
                        title=first(p.get("title")),
                        url=url,
                        company=first(p.get("name")),
                        location=join_loc(*places),
                        posted_at=iso_date(p.get("posted")),
                        remote=bool((p.get("location") or {}).get("fullyRemote")) or None,
                        external_id=first(p.get("id")) or None,
                    ),
                )
        return list(out.values())


class GenericFeed:
    """Any RSS 2.0 / Atom job feed (unknown boards, university vacancy feeds)."""

    id, label, category = "feed", "RSS/Atom feed", "feed"
    terms = "A public RSS/Atom feed published by the site for readers like this one."

    def detect(self, url: str) -> dict[str, Any] | None:
        return (
            {"feed": url}
            if re.search(r"(\.rss|\.xml|/rss|/feed|/atom)(\?|$|/)", url or "", re.I)
            else None
        )

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        url = str(entry.config.get("feed") or entry.url)
        root = _xml(
            await http.text(
                url, robots=True, accept="application/rss+xml, application/atom+xml, text/xml"
            )
        )
        out = []
        for it in _rss_items(root):
            link = _t(it, "link")
            if not link:
                el = next((e for e in it if e.tag.endswith("}link")), None)
                link = (el.get("href") or "") if el is not None else ""
            title = _t(it, "title") or next(
                ((e.text or "").strip() for e in it if e.tag.endswith("}title")), ""
            )
            if not https_url(link) or not title:
                continue
            desc = _t(it, "description") or next(
                (
                    (e.text or "")
                    for e in it
                    if e.tag.endswith("}summary") or e.tag.endswith("}content")
                ),
                "",
            )
            loc = next(
                (
                    (e.text or "").strip()
                    for e in it
                    if e.tag.split("}")[-1] in ("location", "region", "city", "country")
                ),
                "",
            )
            out.append(
                Job(
                    title=title,
                    url=link,
                    company=entry.name,
                    location=loc,
                    description=html_to_text(desc),
                    posted_at=iso_date(
                        _t(it, "pubDate")
                        or next(
                            (
                                (e.text or "")
                                for e in it
                                if e.tag.endswith("}published") or e.tag.endswith("}updated")
                            ),
                            "",
                        )
                    ),
                )
            )
        return out


class JsonLdPage:
    """A careers or vacancies page that publishes schema.org JobPosting data (JSON-LD), as
    Google for Jobs requires. Works for many unknown boards and university vacancy pages."""

    id, label, category = "jsonld", "Web page with JobPosting data", "feed"
    terms = (
        "A public page read once per search, respecting robots.txt; only the structured "
        "JobPosting data the site publishes for search engines is used."
    )

    def detect(self, url: str) -> dict[str, Any] | None:
        return None  # chosen after probing (sources/detect.py)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        import json as _json

        page = await http.text(entry.url, robots=True, accept="text/html")
        out = []
        for block in re.findall(
            r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I
        ):
            try:
                data = _json.loads(block.strip())
            except ValueError:
                continue
            stack = data if isinstance(data, list) else [data]
            while stack:
                node = stack.pop()
                if not isinstance(node, dict):
                    continue
                stack.extend(node.get("@graph") or [])
                stack.extend(
                    x.get("item") for x in node.get("itemListElement") or [] if isinstance(x, dict)
                )
                types = node.get("@type")
                if "JobPosting" not in (types if isinstance(types, list) else [types]):
                    continue
                org = node.get("hiringOrganization") or {}
                locs = node.get("jobLocation") or []
                locs = locs if isinstance(locs, list) else [locs]
                places = []
                for loc in locs:
                    addr = (loc or {}).get("address") or {}
                    if isinstance(addr, dict):
                        country = addr.get("addressCountry")
                        if isinstance(country, dict):
                            country = country.get("name")
                        places.append(join_loc(addr.get("addressLocality"), country))
                remote = node.get("jobLocationType") == "TELECOMMUTE"
                url = https_url(node.get("url")) or entry.url
                out.append(
                    Job(
                        title=first(node.get("title")),
                        url=url,
                        company=first(
                            org.get("name") if isinstance(org, dict) else org, entry.name
                        ),
                        location=join_loc(*places, "Remote" if remote else ""),
                        description=html_to_text(node.get("description")),
                        posted_at=iso_date(node.get("datePosted")),
                        closes_at=iso_date(node.get("validThrough")),
                        remote=remote or None,
                        employment_type=first(node.get("employmentType")) or None,
                    )
                )
        if not out:
            raise SourceError("This page has no schema.org JobPosting data NexScout can read.")
        return out


class Varbi(GenericFeed):
    """Varbi, the recruitment system of most Swedish universities: each has a public RSS feed."""

    id, label, category = "varbi", "Varbi (Swedish universities)", "academic"
    terms = "The university's public vacancy feed on Varbi. Apply on the vacancy page."

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url or "").hostname or "").lower()
        return {"feed": f"https://{host}/en/what:rssfeed/"} if host.endswith(".varbi.com") else None


class Getro(_Board):
    """Getro-powered talent networks (VC portfolio job boards such as b2venture, Cherry Ventures,
    Atomico, Earlybird, Speedinvest). Ported from career-ops providers/getro.mjs."""

    id, label = "getro", "Getro talent network"
    terms = (
        "A venture fund's public portfolio job board (Getro), through the search endpoint its "
        "own page uses. Apply on the company's page."
    )

    def detect(self, url: str) -> dict[str, Any] | None:
        host = (urlsplit(url or "").hostname or "").lower()
        return {} if host.endswith(".getro.com") else None

    async def _collection(self, http: Http, entry: Entry) -> str:
        cid = str(entry.config.get("collection") or entry.config.get("getro_collection") or "")
        if cid.isdigit():
            return cid
        page = await http.text(entry.url, robots=True, accept="text/html")
        m = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        import json as _json

        try:
            nid = (
                (_json.loads(m.group(1)) if m else {})
                .get("props", {})
                .get("pageProps", {})
                .get("network", {})
                .get("id")
            )
        except ValueError:
            nid = None
        if not str(nid or "").isdigit():
            raise SourceError("Couldn't find this Getro board's network id.")
        return str(nid)

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        cid = await self._collection(http, entry)
        origin = f"{urlsplit(entry.url).scheme}://{urlsplit(entry.url).netloc}" if entry.url else ""
        out: list[Job] = []
        total = None
        for page in range(_pages(entry, 10)):
            data = await http.json(
                f"https://api.getro.com/api/v2/collections/{cid}/search/jobs",
                method="POST",
                body={"hitsPerPage": 20, "page": page, "filters": {"page": page}, "query": ""},
                headers={"Referer": f"{origin}/"} if origin else None,
            )
            res = data.get("results") or {}
            jobs = res.get("jobs") or []
            total = res.get("count", total)
            for j in jobs:
                url = https_url(j.get("url"))
                if not url or not first(j.get("title")):
                    continue
                locs = [
                    x
                    for x in (j.get("locations") or j.get("searchable_locations") or [])
                    if isinstance(x, str)
                ]
                remote = str(j.get("work_mode") or "").lower() == "remote"
                out.append(
                    Job(
                        title=first(j.get("title")),
                        url=url,
                        company=first(
                            (j.get("organization") or {}).get("name"),
                            j.get("organization_name"),
                            entry.name,
                        ),
                        location=join_loc(*locs, "Remote" if remote else ""),
                        posted_at=iso_date(j.get("created_at")),
                        remote=remote or None,
                    )
                )
            if not jobs or (isinstance(total, int) and (page + 1) * 20 >= total):
                break
        return out


class WorkInFinland(_Board):
    """Work in Finland (Business Finland): the official board of English-friendly jobs in
    Finland. Its own site reads this public endpoint; robots.txt allows everything."""

    id, label = "workinfinland", "Work in Finland (Business Finland)"
    fixed = ("workinfinland.com", "jobsinfinland.fi")
    terms = (
        "Business Finland's official Work in Finland job board, through the public endpoint "
        "its own page uses. Apply on the employer's or Työmarkkinatori's page."
    )

    async def fetch(self, http: Http, entry: Entry) -> list[Job]:
        params = {}
        if entry.config.get("categories"):
            params["categories"] = ",".join(entry.config["categories"])
        data = await http.json("https://www.workinfinland.com/api/jobs/?" + urlencode(params))
        out = []
        for j in data.get("jobs") or []:
            url, title = https_url(j.get("externalUrl")), first(j.get("title"))
            if not url or not title:
                continue
            emp = j.get("employer") or {}
            out.append(
                Job(
                    title=title,
                    url=url,
                    company=first(emp.get("name"), "Work in Finland"),
                    location=join_loc(emp.get("city"), "Finland"),
                    country="FI",
                    closes_at=iso_date(j.get("expireDate")),
                )
            )
        return out


PROVIDERS: dict[str, Any] = {
    p.id: p
    for p in (
        Varbi(),
        Getro(),
        WorkInFinland(),
        Arbeitnow(),
        TheHub(),
        LandingJobs(),
        JustJoin(),
        SolidJobs(),
        Platsbanken(),
        Arbeitsagentur(),
        Remotive(),
        RemoteOK(),
        WorkingNomads(),
        Jobicy(),
        Himalayas(),
        FourDayWeek(),
        WeWorkRemotely(),
        NoFluffJobs(),
        GenericFeed(),
        JsonLdPage(),
    )
}
