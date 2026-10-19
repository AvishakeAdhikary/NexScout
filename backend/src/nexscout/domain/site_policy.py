"""Which sites NexScout may automate, and how (pure; AGENTS.md §4 online-compliance guardrails).

Three modes:
- `auto`: NexScout may fill (and, if the user's policy allows, submit) without asking first.
- `approval`: NexScout may fill, but a person approves the submission.
- `manual`: NexScout doesn't automate this site at all; it tells the user to apply themselves.

Sites whose published terms prohibit bots, scraping or automated applications are `manual`,
whatever the user's settings. So is any page that robots.txt disallows for NexScout. CAPTCHAs
and logins are never bypassed anywhere (see domain/forms.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

# Published terms that forbid automated access or applications (checked 2026-10; conservative).
# Matching is by registrable suffix, so "uk.linkedin.com" matches "linkedin.com".
MANUAL_ONLY: dict[str, str] = {
    "linkedin.com": "LinkedIn's User Agreement prohibits bots and automated activity.",
    "indeed.com": "Indeed's terms prohibit automated applications and scraping.",
    "glassdoor.com": "Glassdoor's terms prohibit automated access.",
    "ziprecruiter.com": "ZipRecruiter's terms prohibit automated access.",
    "monster.com": "Monster's terms prohibit automated access.",
    "joinhandshake.com": "Handshake's terms prohibit automated access.",
    "wellfound.com": "Wellfound's terms prohibit automated applications.",
    "angel.co": "Wellfound's terms prohibit automated applications.",
    "facebook.com": "Meta's terms prohibit automated access.",
    "instagram.com": "Meta's terms prohibit automated access.",
    "x.com": "X's terms prohibit automated access without permission.",
    "twitter.com": "X's terms prohibit automated access without permission.",
    "researchgate.net": "ResearchGate's terms prohibit automated access.",
    "scholar.google.com": "Google Scholar doesn't permit automated access.",
    "upwork.com": "Upwork's terms prohibit automated proposals.",
    "fiverr.com": "Fiverr's terms prohibit automated activity.",
}

# Hosts that commonly run application forms for many employers (applicant tracking systems).
# Not banned, but each employer's portal has its own terms, so submissions there always get a
# human approval unless the user explicitly allowed auto-submit on such portals.
ATS_HOSTS: tuple[str, ...] = (
    "myworkdayjobs.com",
    "workday.com",
    "greenhouse.io",
    "lever.co",
    "smartrecruiters.com",
    "icims.com",
    "taleo.net",
    "successfactors.com",
    "ashbyhq.com",
    "jobvite.com",
)


@dataclass(frozen=True)
class SiteVerdict:
    mode: str  # auto | approval | manual
    reason: str
    host: str


def host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def site_verdict(
    url: str,
    *,
    robots_allows: bool | None,
    demo_origin: str | None = None,
    allow_ats_auto: bool = False,
) -> SiteVerdict:
    """Decide how NexScout may treat an application page. `robots_allows` is None when it
    couldn't be checked (treated as "ask a person")."""
    host = host_of(url)
    if not host or urlsplit(url).scheme not in ("http", "https"):
        return SiteVerdict("manual", "Not a web address NexScout can open.", host)
    if demo_origin and url.lower().startswith(demo_origin.lower().rstrip("/") + "/"):
        return SiteVerdict("auto", "NexScout's labelled demo application site.", host)
    for domain, why in MANUAL_ONLY.items():
        if host_matches(host, domain):
            return SiteVerdict("manual", f"{why} Apply on the site yourself.", host)
    if robots_allows is False:
        return SiteVerdict(
            "manual", "The site's robots.txt asks automated tools not to open this page.", host
        )
    if urlsplit(url).scheme != "https":
        return SiteVerdict("approval", "The page isn't encrypted (http), so a person checks.", host)
    if robots_allows is None:
        return SiteVerdict(
            "approval", "Couldn't read the site's robots.txt, so a person checks.", host
        )
    if any(host_matches(host, d) for d in ATS_HOSTS) and not allow_ats_auto:
        return SiteVerdict(
            "approval", "An employer's application portal: a person approves each submission.", host
        )
    return SiteVerdict("auto", "No published restriction on automated applications found.", host)
