"""Eligibility signals read from a posting's own text (pure, deterministic).

What a posting says about visas, work authorization, required local languages, funding and fees.
Signals are only ever *read* from the text: a posting that says nothing gives "not stated", never
a guess. The sponsorship vocabularies are ported from career-ops (MIT, scan.mjs
DEFAULT_VISA_POSITIVE/NEGATIVE; see THIRD_PARTY_NOTICES.md) and extended for EU postings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SPONSOR_POSITIVE = (
    "visa sponsorship",
    "sponsor a visa",
    "sponsor visas",
    "will sponsor",
    "sponsorship available",
    "sponsorship is available",
    "eligible for sponsorship",
    "provide sponsorship",
    "offer sponsorship",
    "immigration support",
    "h-1b",
    "h1b",
    "o-1 visa",
    "employment pass",
    "eu blue card",
    "blue card",
    "skilled worker visa",
    "skilled worker sponsorship",
    "work permit support",
    "help with your work permit",
    "assist with visa",
    "relocation and visa",
    "visa support",
    "specialist residence permit",
    "residence permit support",
    "we sponsor",
    "talent boost",
)
SPONSOR_NEGATIVE = (
    "no visa sponsorship",
    "no sponsorship",
    "without sponsorship",
    "unable to sponsor",
    "not able to sponsor",
    "cannot sponsor",
    "do not sponsor",
    "does not sponsor",
    "not offer sponsorship",
    "not provide sponsorship",
    "sponsorship is not available",
    "sponsorship not available",
    "not offer visa sponsorship",
    "citizens and permanent residents only",
    "permanent residents only",
)
# Postings that require existing rights to work locally (EU-style wording).
AUTHORIZATION_REQUIRED = (
    "eu citizens only",
    "eu citizenship required",
    "must be an eu citizen",
    "must have eu work authorization",
    "must have the right to work",
    "must already have the right to work",
    "existing right to work",
    "valid work permit required",
    "must hold a valid work permit",
    "eu/eea citizens only",
    "eea citizens only",
    "only candidates with the right to work",
    "security clearance",
)
RELOCATION = (
    "relocation package",
    "relocation support",
    "relocation assistance",
    "help you relocate",
    "relocation bonus",
)
# A local language required to a working level.
LANGUAGE_REQUIRED = {
    "fi": (
        "fluent finnish",
        "finnish fluency",
        "fluency in finnish",
        "sujuva suomen kieli",
        "suomen kielen taito",
        "excellent finnish",
        "native finnish",
        "finnish is required",
        "finnish language skills are required",
        "proficiency in finnish",
    ),
    "sv": (
        "fluent swedish",
        "swedish fluency",
        "fluency in swedish",
        "swedish is required",
        "flytande svenska",
    ),
    "de": (
        "fluent german",
        "german fluency",
        "fluency in german",
        "german is required",
        "sehr gute deutschkenntnisse",
        "fließend deutsch",
        "fliessend deutsch",
        "verhandlungssicheres deutsch",
        "german (c1",
        "german c1",
        "german (c2",
    ),
    "nl": (
        "fluent dutch",
        "dutch fluency",
        "fluency in dutch",
        "dutch is required",
        "vloeiend nederlands",
    ),
    "fr": (
        "fluent french",
        "french fluency",
        "fluency in french",
        "french is required",
        "français courant",
        "francais courant",
    ),
    "da": ("fluent danish", "danish is required"),
    "no": ("fluent norwegian", "norwegian is required"),
    "it": ("fluent italian", "italian is required"),
    "es": ("fluent spanish", "spanish is required"),
    "pl": ("fluent polish", "polish is required"),
    "pt": ("fluent portuguese",),
}
FUNDED = (
    "fully funded",
    "full funding",
    "funded position",
    "funded phd",
    "salaried position",
    "employment contract",
    "doctoral researcher position",
    "monthly salary",
    "stipend",
    "scholarship covers",
    "tuition fee waiver",
    "tuition waiver",
    "studentship",
    "marie skłodowska-curie",
    "marie sklodowska-curie",
    "msca",
    "salary is based on",
    "the salary",
    "gross salary",
    "per month",
)
UNFUNDED = (
    "self-funded",
    "self funded",
    "no funding",
    "unfunded",
    "funding is not available",
    "applicants must secure their own funding",
    "tuition fees apply",
)

_MONEY = re.compile(
    r"(?P<cur>€|eur|euro|euros|£|gbp|\$|usd|chf|sek|nok|dkk|pln|czk|inr|₹)\s?"
    r"(?P<amt>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,2})?(?!\d))"
    r"|(?P<amt2>(?:\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,]\d{1,2})?(?!\d))\s?"
    r"(?P<cur2>€|eur|euro|euros|gbp|usd|chf|sek|nok|dkk|pln|czk|inr)(?![a-z])",
    re.I,
)
_FEE_CONTEXT = re.compile(
    r"(application fee|application charge|tuition|tuition fee|deposit|"
    r"processing fee|admission fee)",
    re.I,
)
_CURRENCY = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "$": "USD",
    "usd": "USD",
    "chf": "CHF",
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "pln": "PLN",
    "czk": "CZK",
    "inr": "INR",
    "₹": "INR",
}


@dataclass
class Fee:
    kind: str  # application_fee | tuition | deposit | other
    amount: float
    currency: str
    quote: str


@dataclass
class Signals:
    sponsorship: str = "not_stated"  # offered | refused | not_stated
    authorization_required: bool = False
    relocation: bool = False
    languages_required: list[str] = field(default_factory=list)  # ISO 639-1 codes
    funding: str = "not_stated"  # funded | unfunded | not_stated
    fees: list[Fee] = field(default_factory=list)
    quotes: dict[str, str] = field(default_factory=dict)  # signal → the words that triggered it


def _find(text: str, phrases: tuple[str, ...]) -> str | None:
    for p in phrases:
        i = text.find(p)
        if i >= 0:
            return p
    return None


# Words that make a language a bonus, not a requirement ("fluent German is a plus").
_OPTIONAL = re.compile(
    r"\b(a plus|nice[- ]to[- ]have|an advantage|advantageous|beneficial|bonus|"
    r"preferred|desirable|is an asset|not required|not a requirement|not necessary|helpful|"
    r"von vorteil|wünschenswert|meriterande|en fördel|eduksi|un atout|een pluspunt)\b",
    re.I,
)


def required_languages(low: str) -> dict[str, str]:
    """Languages a (lowercased, whitespace-collapsed) text requires: language code -> the
    phrase. A mention next to "a plus", "nice to have", "not required"... doesn't count."""
    out: dict[str, str] = {}
    for lang, phrases in LANGUAGE_REQUIRED.items():
        for p in phrases:
            for m in re.finditer(re.escape(p), low):
                end = low.find(".", m.end())
                sentence = low[max(0, low.rfind(".", 0, m.start()) + 1) : end if end > 0 else None]
                if not _OPTIONAL.search(sentence):
                    out.setdefault(lang, p)
                    break
            if lang in out:
                break
    return out


def _amount(raw: str) -> float | None:
    s = raw.replace(" ", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):  # 1.234.567 / 1,234,567
        s = re.sub(r"[.,]", "", s)
    else:
        s = s.replace(",", ".") if s.count(",") == 1 and "." not in s else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def read_signals(text: str | None) -> Signals:
    """All signals found in a posting's text. Empty text → everything "not stated"."""
    out = Signals()
    if not text:
        return out
    low = " ".join(text.lower().split())
    if (q := _find(low, SPONSOR_NEGATIVE)) is not None:
        out.sponsorship, out.quotes["sponsorship"] = "refused", q
    elif (q := _find(low, SPONSOR_POSITIVE)) is not None:
        out.sponsorship, out.quotes["sponsorship"] = "offered", q
    if (q := _find(low, AUTHORIZATION_REQUIRED)) is not None:
        out.authorization_required, out.quotes["authorization"] = True, q
    if (q := _find(low, RELOCATION)) is not None:
        out.relocation, out.quotes["relocation"] = True, q
    for lang, q in required_languages(low).items():
        out.languages_required.append(lang)
        out.quotes[f"language:{lang}"] = q
    if (q := _find(low, UNFUNDED)) is not None:
        out.funding, out.quotes["funding"] = "unfunded", q
    elif (q := _find(low, FUNDED)) is not None:
        out.funding, out.quotes["funding"] = "funded", q
    for ctx in _FEE_CONTEXT.finditer(low):
        window = low[ctx.start() : ctx.end() + 80]
        m = _MONEY.search(window)
        if not m:
            continue
        cur = (m.group("cur") or m.group("cur2") or "").lower()
        amt = _amount(m.group("amt") or m.group("amt2") or "")
        if amt is None or cur not in _CURRENCY:
            continue
        word = ctx.group(1)
        kind = (
            "application_fee"
            if "application" in word or "processing" in word or "admission" in word
            else "deposit"
            if "deposit" in word
            else "tuition"
        )
        out.fees.append(Fee(kind, amt, _CURRENCY[cur], window[:120].strip()))
    return out
