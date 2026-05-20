"""Apply-side policy — skip lists & URL filters (§13.5 + §22).

Reads the shipped ``discovery/sites.yaml`` for:

* ``manual_ats`` — hosts where CAPTCHAs are unsolvable; we never even attempt.
* ``blocked.sites`` / ``blocked.url_patterns`` — handed to the atomic acquire
  query in the orchestrator.
* ``blocked_sso`` — login hosts that immediately fail ``RESULT:sso_required``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass
class ApplyPolicy:
    """Loaded apply-side policy. Immutable per-process."""

    manual_ats: list[str] = field(default_factory=list)
    blocked_sites: list[str] = field(default_factory=list)
    blocked_url_patterns: list[str] = field(default_factory=list)
    blocked_sso: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def is_manual_ats(self, url: str | None) -> bool:
        """Return True if ``url``'s host is in the manual-ATS skip list."""
        if not url:
            return False
        host = _host(url)
        return any(_host_matches(host, m) for m in self.manual_ats)

    def is_blocked_site(self, site: str | None) -> bool:
        if not site:
            return False
        s = site.strip().lower()
        return any(s == b.lower() for b in self.blocked_sites)

    def is_blocked_sso(self, url: str | None) -> bool:
        """Return True if the URL's host matches a blocked SSO provider."""
        if not url:
            return False
        host = _host(url)
        return any(_host_matches(host, sso) for sso in self.blocked_sso)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _sites_yaml_default() -> Path:
    """Return the shipped sites.yaml path (under ``discovery/``)."""
    return Path(__file__).resolve().parent.parent / "discovery" / "sites.yaml"


@lru_cache(maxsize=4)
def load_policy(path: str | None = None) -> ApplyPolicy:
    """Read sites.yaml and return an :class:`ApplyPolicy`."""
    p = Path(path) if path else _sites_yaml_default()
    if not p.exists():
        return ApplyPolicy()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return policy_from_dict(data)


def policy_from_dict(data: dict[str, Any]) -> ApplyPolicy:
    """Convert a raw sites.yaml dict into an :class:`ApplyPolicy`."""
    manual = list(data.get("manual_ats") or [])
    blocked = data.get("blocked") or {}
    blocked_sites = list(blocked.get("sites") or [])
    blocked_patterns = list(blocked.get("url_patterns") or [])
    blocked_sso = list(data.get("blocked_sso") or [])
    return ApplyPolicy(
        manual_ats=[str(x) for x in manual],
        blocked_sites=[str(x) for x in blocked_sites],
        blocked_url_patterns=[str(x) for x in blocked_patterns],
        blocked_sso=[str(x) for x in blocked_sso],
    )


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except (ValueError, TypeError):
        return ""


def _host_matches(host: str, candidate: str) -> bool:
    """Return True if ``host`` equals ``candidate`` or is a sub-domain of it."""
    h = host.lower()
    c = candidate.lower().lstrip(".")
    if not h or not c:
        return False
    return h == c or h.endswith("." + c)


__all__ = [
    "ApplyPolicy",
    "load_policy",
    "policy_from_dict",
]
