"""Countries (ISO 3166-1 alpha-2) and free-text location resolution (pure).

Every country NexScout stores or compares is an ISO alpha-2 code ("FI", "GB"). Groups ("EU",
"NORDICS", "EUROPE", …) expand to codes. Job sources describe locations in free text
("Espoo, Finland", "Remote - EU", "München"); `resolve_location` turns that into codes, or
returns nothing rather than guessing.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Any


def _fold(text: str) -> str:
    """Lowercase, accents removed ("München" → "munchen")."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in norm if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    raw = resources.files("nexscout.domain.geo_data").joinpath("countries.json").read_text("utf-8")
    data: dict[str, Any] = json.loads(raw)
    return data


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    continent: str


@lru_cache(maxsize=1)
def countries() -> dict[str, Country]:
    return {c["code"]: Country(c["code"], c["name"], c["continent"]) for c in _data()["countries"]}


@lru_cache(maxsize=1)
def groups() -> dict[str, tuple[str, tuple[str, ...]]]:
    return {k: (v["name"], tuple(v["codes"])) for k, v in _data()["groups"].items()}


def is_country(code: str) -> bool:
    return code.upper() in countries()


def country_names(codes: list[str] | tuple[str, ...]) -> str:
    """Codes as readable names for messages ("DE, FI" -> "Germany, Finland")."""
    known = countries()
    return ", ".join(known[c].name if c in known else c for c in codes)


def expand(values: list[str] | tuple[str, ...] | set[str]) -> set[str]:
    """Codes and group keys → country codes. Unknown entries are ignored (validated on input)."""
    out: set[str] = set()
    g = groups()
    for v in values:
        key = v.strip().upper()
        if key in g:
            out.update(g[key][1])
        elif key in countries():
            out.add(key)
    return out


def normalize_list(values: list[str]) -> tuple[list[str], list[str]]:
    """User input (codes, group keys or country names) → (valid codes/groups, unknown entries)."""
    ok: list[str] = []
    unknown: list[str] = []
    for v in values:
        key = v.strip().upper()
        if not key:
            continue
        if key in groups() or key in countries():
            ok.append(key)
            continue
        found = resolve_location(v).countries
        if len(found) == 1 and _fold(v).strip() in _name_index():
            ok.append(found[0])
        else:
            unknown.append(v.strip())
    return list(dict.fromkeys(ok)), unknown


@lru_cache(maxsize=1)
def _name_index() -> dict[str, str]:
    """Folded country name/alias → code (names only, no cities)."""
    idx: dict[str, str] = {}
    for c in _data()["countries"]:
        for n in [c["name"], *c["aliases"]]:
            idx.setdefault(_fold(n), c["code"])
    return idx


# City names that are also ordinary words: matched only when written with a capital letter.
_AMBIGUOUS = frozenset(
    {
        "nice",
        "reading",
        "bath",
        "split",
        "york",
        "mobile",
        "lund",
        "bonn",
        "lahti",
        "pori",
        "vaasa",
        "graz",
        "linz",
        "cork",
        "basel",
        "zug",
        "bern",
        "delft",
        "leiden",
        "aachen",
        "jena",
        "turin",
        "padua",
    }
)


@lru_cache(maxsize=1)
def _patterns() -> list[tuple[re.Pattern[str], str]]:
    """Whole-word patterns for names, aliases and cities, longest first (so "Northern
    Ireland" wins over "Ireland")."""
    terms: dict[str, str] = {}
    for c in _data()["countries"]:
        for n in [c["name"], *c["aliases"], *c["cities"]]:
            f = _fold(n)
            if len(f) >= 3:
                terms.setdefault(f, c["code"])
    ordered = sorted(terms.items(), key=lambda kv: -len(kv[0]))
    return [(re.compile(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])"), code) for t, code in ordered]


REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh|distributed|telecommute|etätyö)\b")
_SCOPES = {
    "eu": "EU",
    "europe": "EUROPE",
    "european union": "EU",
    "emea": "EUROPE",
    "eea": "EEA",
    "nordics": "NORDICS",
    "nordic": "NORDICS",
    "scandinavia": "NORDICS",
    "dach": "DACH",
    "benelux": "BENELUX",
    "baltics": "BALTICS",
    "worldwide": "WORLD",
    "global": "WORLD",
    "anywhere": "WORLD",
}
_SCOPE_RE = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, _SCOPES), key=len, reverse=True)) + r")\b"
)
_CODE_TAIL = re.compile(r"(?:,|\(|\s-\s)\s*([A-Z]{2})\s*\)?\s*$")


@dataclass(frozen=True)
class GeoResult:
    countries: list[str] = field(default_factory=list)  # ISO codes, in order of mention
    remote: bool = False
    remote_scope: str | None = None  # a group key ("EU", "EUROPE", "WORLD") or a country code

    @property
    def primary(self) -> str | None:
        return self.countries[0] if self.countries else None


def resolve_location(text: str | None) -> GeoResult:
    """Free-text location → ISO codes. Unknown text resolves to no country (never a guess)."""
    if not text or not text.strip():
        return GeoResult()
    folded = _fold(text)
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for pat, code in _patterns():
        for m in pat.finditer(folded):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue  # inside a longer match ("Northern Ireland" contains "Ireland")
            if m.group(0) in _AMBIGUOUS and not text[m.start()].isupper():
                continue  # "somewhere nice" is not Nice, France
            taken.append((m.start(), m.end()))
            found.append((m.start(), code))
    tail = _CODE_TAIL.search(text.strip())
    if tail and tail.group(1) in countries() and not found:
        found.append((len(folded), tail.group(1)))
    ordered = list(dict.fromkeys(code for _, code in sorted(found)))
    remote = bool(REMOTE.search(folded))
    scope = None
    if remote:
        scope_m = _SCOPE_RE.search(folded)
        if scope_m:
            scope = _SCOPES[scope_m.group(1)]
        elif len(ordered) == 1:
            scope = ordered[0]
    return GeoResult(ordered, remote, scope)


def in_area(result: GeoResult, area: set[str]) -> bool | None:
    """Does a location fall in `area` (codes)? None when the location is unknown."""
    if result.countries:
        return any(c in area for c in result.countries)
    if result.remote and result.remote_scope:
        if result.remote_scope == "WORLD":
            return True
        scope = expand([result.remote_scope])
        return bool(scope & area)
    return None
