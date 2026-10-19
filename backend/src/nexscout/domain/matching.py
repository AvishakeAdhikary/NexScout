"""Explainable, deterministic opportunity matching (spec §6.4).

A score is a decision-support estimate. It is never a prediction of being hired or admitted.
Every point of the score comes from a named factor with a plain-language explanation and the
fact ids that support it, and every shortfall is listed as a gap.

Protected or sensitive characteristics can't influence scoring by construction:
`CandidateSummary` has no field for them. Work authorization is used only when the user opted
in, and only as an explicit eligibility check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from nexscout.domain.fx import convert as fx_convert
from nexscout.domain.geo import GeoResult, country_names, expand, in_area, resolve_location
from nexscout.domain.opportunities import (
    ACADEMIC_KINDS,
    NormalizedOpportunity,
    OpportunityKind,
    Remote,
    Sponsorship,
    normalize_title,
)
from nexscout.domain.preferences import ExperienceMode, Preferences
from nexscout.domain.profile import PRESENT, Section
from nexscout.domain.requirements import LANGUAGE_NAMES, read_requirements, skills_in
from nexscout.domain.signals import read_signals

DEGREE_LEVELS = {"high_school": 1, "associate": 2, "bachelor": 3, "master": 4, "phd": 5}
_DEGREE_PATTERNS: list[tuple[str, str]] = [
    (r"ph\.?\s?d|doctor|d\.?phil|doctorate", "phd"),
    (r"master|m\.?\s?sc|m\.?\s?eng|m\.?\s?a\b|mba|m\.?\s?tech|m\.?\s?phil|msc|meng", "master"),
    (r"bachelor|b\.?\s?sc|b\.?\s?eng|b\.?\s?a\b|b\.?\s?tech|b\.?\s?s\b|bsc|beng", "bachelor"),
    (r"associate", "associate"),
    (r"high school|a-levels|gcse|secondary", "high_school"),
]


def degree_level(text: str | None) -> str | None:
    if not text:
        return None
    for pattern, level in _DEGREE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return level
    return None


@dataclass(frozen=True)
class Experience:
    fact_id: str
    title: str
    start: str | None
    end: str | None


@dataclass
class CandidateSummary:
    """Only job-relevant, user-confirmed information. No protected attributes exist here."""

    skills: dict[str, str] = field(default_factory=dict)  # lowercase name -> fact id
    employment: list[Experience] = field(default_factory=list)
    research: list[Experience] = field(default_factory=list)
    degrees: list[tuple[str, str]] = field(default_factory=list)  # (level, fact id)
    research_topics: list[tuple[str, str]] = field(default_factory=list)  # (text, fact id)
    preferences: Preferences = field(default_factory=Preferences)
    work_authorization: list[str] = field(default_factory=list)  # ISO codes; only if opted in
    fx_rates: dict[str, float] = field(default_factory=dict)  # ECB: units per 1 EUR


def summarize(
    facts: list[tuple[str, Section, dict[str, Any]]], preferences: Preferences
) -> CandidateSummary:
    """Build the matcher input from *accepted* facts only."""
    s = CandidateSummary(preferences=preferences)
    if preferences.sensitive.use_for_eligibility:
        from nexscout.domain.geo import normalize_list

        s.work_authorization = normalize_list(preferences.sensitive.work_authorization)[0]
    for fid, section, data in facts:
        if section is Section.SKILL:
            s.skills.setdefault(str(data["name"]).lower(), fid)
        elif section is Section.PROJECT:
            for tech in data.get("technologies", []):
                s.skills.setdefault(str(tech).lower(), fid)
        elif section is Section.EMPLOYMENT:
            s.employment.append(
                Experience(fid, str(data.get("title", "")), data.get("start"), data.get("end"))
            )
        elif section is Section.RESEARCH:
            s.research.append(
                Experience(fid, str(data.get("title", "")), data.get("start"), data.get("end"))
            )
            s.research_topics.append(
                (f"{data.get('title', '')} {data.get('description', '')}", fid)
            )
        elif section is Section.EDUCATION:
            level = degree_level(data.get("degree"))
            if level:
                s.degrees.append((level, fid))
            if data.get("field_of_study"):
                s.research_topics.append((str(data["field_of_study"]), fid))
        elif section is Section.PUBLICATION:
            s.research_topics.append((str(data.get("title", "")), fid))
    return s


def _to_months(value: str | None, today: date) -> int | None:
    if not value:
        return None
    if value == PRESENT:
        return today.year * 12 + today.month - 1
    parts = value.split("-")
    year = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else 1
    return year * 12 + month - 1


def years_of_experience(entries: list[Experience], today: date) -> tuple[float, bool]:
    """Total years across entries with overlapping periods merged.

    Returns (years, complete): `complete` is False if some entries lack dates (not counted).
    """
    intervals: list[tuple[int, int]] = []
    complete = True
    for e in entries:
        start, end = _to_months(e.start, today), _to_months(e.end, today)
        if start is None:
            complete = False
            continue
        if end is None:  # a start without an end: count one year at most, flag incomplete
            end, complete = start + 12, False
        if end >= start:
            intervals.append((start, end + 1))
    intervals.sort()
    total, cur_s, cur_e = 0, None, None
    for s_, e_ in intervals:
        if cur_e is None or s_ > cur_e:
            if cur_e is not None and cur_s is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s_, e_
        else:
            cur_e = max(cur_e, e_)
    if cur_e is not None and cur_s is not None:
        total += cur_e - cur_s
    return round(total / 12, 1), complete


@dataclass
class Factor:
    name: str
    weight: int
    points: float
    explanation: str
    fact_ids: list[str] = field(default_factory=list)


@dataclass
class Gap:
    code: str
    severity: str  # "blocker" | "gap" | "info"
    message: str


@dataclass
class MatchResult:
    score: int
    eligible: bool
    mode: str
    factors: list[Factor]
    gaps: list[Gap]


def _norm_skill(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]", "", s.lower())


def _opp_geo(opp: NormalizedOpportunity) -> GeoResult:
    """Countries for a posting: stored codes, else resolved from its location fields."""
    if opp.country_codes:
        return GeoResult(list(opp.country_codes), opp.remote is Remote.REMOTE, opp.remote_scope)
    text = " ; ".join(
        x
        for x in (opp.location_text, opp.location_city, opp.location_region, opp.location_country)
        if x
    )
    found = resolve_location(text)
    return GeoResult(
        found.countries, found.remote or opp.remote is Remote.REMOTE, found.remote_scope
    )


def match(opp: NormalizedOpportunity, cand: CandidateSummary, today: date) -> MatchResult:
    prefs = cand.preferences
    mode = prefs.experience_mode
    factors: list[Factor] = []
    gaps: list[Gap] = []
    eligible = True
    skills_by_norm = {_norm_skill(k): fid for k, fid in cand.skills.items()}
    req = read_requirements(opp.title, opp.description)
    # The candidate's skills in the vocabulary's names too ("LLM fine-tuning" -> LLMs,
    # Fine-tuning), so a posting's wording and the profile's wording meet.
    for k, fid in cand.skills.items():
        for canon in skills_in(k):
            skills_by_norm.setdefault(_norm_skill(canon), fid)

    # --- Skills (35)
    required = [s for s in opp.required_skills if s.strip()]
    mentioned = (
        skills_in(f"{opp.title}\n{opp.description}", extra=list(cand.skills))
        if not required and opp.description
        else []
    )
    if not required and len(mentioned) >= 2:
        hits = [
            (s, skills_by_norm[_norm_skill(s)])
            for s in mentioned
            if _norm_skill(s) in skills_by_norm
        ]
        missing = [s for s in mentioned if _norm_skill(s) not in skills_by_norm]
        factors.append(
            Factor(
                "Skills",
                35,
                35 * (0.3 + 0.7 * len(hits) / len(mentioned)),
                f"The posting mentions {len(mentioned)} skills; you list {len(hits)}"
                + (f": {', '.join(s for s, _ in hits[:8])}." if hits else "."),
                list(dict.fromkeys(fid for _, fid in hits)),
            )
        )
        if missing:
            gaps.append(
                Gap(
                    "missing_skills",
                    "gap",
                    f"Mentioned in the posting, not on your profile: {', '.join(missing[:8])}.",
                )
            )
    elif required:
        hits = [
            (s, skills_by_norm[_norm_skill(s)])
            for s in required
            if _norm_skill(s) in skills_by_norm
        ]
        missing = [s for s in required if _norm_skill(s) not in skills_by_norm]
        pts = 35 * len(hits) / len(required)
        factors.append(
            Factor(
                "Skills",
                35,
                pts,
                f"You list {len(hits)} of {len(required)} required skills"
                + (f": {', '.join(s for s, _ in hits)}." if hits else "."),
                [fid for _, fid in hits],
            )
        )
        if missing:
            gaps.append(
                Gap(
                    "missing_skills",
                    "gap",
                    f"Required skills not on your profile: {', '.join(missing)}.",
                )
            )
    else:
        factors.append(
            Factor(
                "Skills", 35, 17.5, "The posting doesn't list required skills; scored as neutral."
            )
        )
    preferred_hits = [s for s in opp.preferred_skills if _norm_skill(s) in skills_by_norm]
    if preferred_hits:
        factors[-1].explanation += f" Also matches preferred: {', '.join(preferred_hits)}."

    # --- Experience (20)
    exp_entries = cand.employment + (cand.research if opp.kind in ACADEMIC_KINDS else [])
    years, complete = years_of_experience(exp_entries, today)
    need = opp.experience_min_years
    asked = ""
    if need is None and req.min_years is not None:
        need, asked = req.min_years, f' ("{req.years_quote}")'
    exp_ids = [e.fact_id for e in exp_entries]
    if need is None and req.seniority == "senior" and opp.kind not in ACADEMIC_KINDS:
        enough = years >= 5
        factors.append(
            Factor(
                "Experience",
                20,
                20 if enough else 20 * max(0.4, years / 5),
                f"The title says {req.seniority_word}; such roles usually expect about 5 years.",
                exp_ids,
            )
        )
        if not enough:
            gaps.append(
                Gap(
                    "senior_title",
                    "gap",
                    f"The title says {req.seniority_word}: usually about 5+ years. You have "
                    f"about {years:g}.",
                )
            )
    elif need is None:
        factors.append(
            Factor(
                "Experience",
                20,
                20 if exp_entries or opp.kind in ACADEMIC_KINDS else 10,
                "No minimum experience stated.",
                exp_ids,
            )
        )
    elif years >= need:
        factors.append(
            Factor(
                "Experience",
                20,
                20,
                f"About {years:g} years of experience; {need:g}+ requested{asked}.",
                exp_ids,
            )
        )
    else:
        short = round(need - years, 1)
        note = "" if complete else " Some entries have no dates and weren't counted."
        if mode is ExperienceMode.STRICT:
            eligible = False
            gaps.append(
                Gap(
                    "experience_below_minimum",
                    "blocker",
                    f"Asks for {need:g}+ years{asked}; you have about {years:g}.{note} "
                    "Hidden in strict mode. Switch to flexible mode to see stretch roles.",
                )
            )
        else:
            gaps.append(
                Gap(
                    "experience_below_minimum",
                    "gap",
                    f"Stretch role: asks for {need:g}+ years{asked}, you have about "
                    f"{years:g} ({short:g} short).{note}",
                )
            )
        factors.append(
            Factor(
                "Experience",
                20,
                20 * min(1.0, years / need) * 0.6,
                f"About {years:g} years vs {need:g}+ requested.",
                exp_ids,
            )
        )

    # --- Education (10)
    best = max((DEGREE_LEVELS[lvl] for lvl, _ in cand.degrees), default=0)
    best_ids = [fid for lvl, fid in cand.degrees if DEGREE_LEVELS[lvl] == best]
    req_level = (opp.education_level or "").lower() or ("phd" if req.needs_doctorate else None)
    if req_level and req_level in DEGREE_LEVELS:
        if best >= DEGREE_LEVELS[req_level]:
            factors.append(
                Factor("Education", 10, 10, f"Meets the {req_level} requirement.", best_ids)
            )
        elif req.needs_doctorate and not opp.education_level:
            # A postdoc is for people who already hold a doctorate.
            factors.append(Factor("Education", 10, 0, "A postdoc needs a doctorate.", []))
            known = bool(cand.degrees)
            gaps.append(
                Gap(
                    "doctorate_required",
                    "blocker" if known else "gap",
                    "A postdoc position needs a completed doctorate"
                    + (", which isn't on your profile." if known else "; add your degrees."),
                )
            )
            if known:
                eligible = False
        else:
            factors.append(Factor("Education", 10, 0, f"Requires a {req_level} degree.", []))
            gaps.append(
                Gap(
                    "education_below_requirement",
                    "gap",
                    f"Requires a {req_level} degree, which isn't on your confirmed profile.",
                )
            )
    else:
        factors.append(
            Factor(
                "Education",
                10,
                10 if best else 5,
                "No specific degree requirement stated.",
                best_ids,
            )
        )

    # --- Location (15): ISO codes and groups, include and exclude lists
    geo = _opp_geo(opp)
    area_in = expand(prefs.countries)
    area_out = expand(prefs.countries_exclude)
    cities = {c.lower() for c in prefs.cities}
    where = (
        opp.location_text
        or ", ".join(x for x in (opp.location_city, opp.location_country) if x)
        or "unknown location"
    )
    names = country_names(geo.countries)
    if geo.countries and area_out and all(c in area_out for c in geo.countries):
        eligible = False
        factors.append(Factor("Location", 15, 0, f"{names} is on your excluded list."))
        gaps.append(Gap("excluded_country", "blocker", f"In {names}, which you excluded."))
    elif not area_in and not cities:
        factors.append(Factor("Location", 15, 15, "You haven't limited the countries."))
    elif (opp.location_city or "").lower() in cities and opp.location_city:
        factors.append(Factor("Location", 15, 15, f"{opp.location_city} is a city you chose."))
    elif area_in and (inside := in_area(geo, area_in)) is not None:
        if inside:
            label = names or ("Remote" if geo.remote else where)
            factors.append(Factor("Location", 15, 15, f"{label} is in your chosen countries."))
        else:
            factors.append(
                Factor("Location", 15, 0, f"{names or where} isn't in your chosen countries.")
            )
            gaps.append(
                Gap(
                    "outside_countries",
                    "blocker",
                    f"In {names or where}, outside the countries you chose.",
                )
            )
            eligible = False
    else:
        factors.append(
            Factor(
                "Location", 15, 7, f"Location ({where}) couldn't be placed in a country; check it."
            )
        )
        gaps.append(
            Gap(
                "location_unknown",
                "info",
                f"The posting's location ({where}) doesn't name a country NexScout recognizes.",
            )
        )
    if prefs.remote == "remote" and opp.remote in (Remote.ONSITE,):
        gaps.append(Gap("onsite_role", "info", "On-site role; you prefer remote work."))

    # --- Role / research alignment (15)
    title_tokens = set(normalize_title(opp.title).split())
    if opp.kind in ACADEMIC_KINDS:
        areas = [a.lower() for a in prefs.research_areas] + [a.lower() for a in prefs.disciplines]
        opp_text = " ".join([opp.title, " ".join(opp.research_areas), opp.description]).lower()
        hit_areas = [a for a in areas if a and a in opp_text]
        topic_ids = [
            fid
            for text, fid in cand.research_topics
            if set(normalize_title(text).split())
            & set(normalize_title(" ".join(opp.research_areas) or opp.title).split())
        ]
        pts = 15 if hit_areas else (8 if topic_ids else 0)
        expl = (
            f"Matches your research interests: {', '.join(hit_areas)}."
            if hit_areas
            else "Related to topics in your profile."
            if topic_ids
            else "No overlap with your stated research interests."
        )
        factors.append(Factor("Research fit", 15, pts, expl, topic_ids))
    else:
        wanted = [normalize_title(t) for t in prefs.job_titles]
        past = [(normalize_title(e.title), e.fact_id) for e in cand.employment]
        want_hit = any(
            set(w.split()) <= title_tokens or title_tokens <= set(w.split()) for w in wanted if w
        )
        past_ids = [fid for t, fid in past if len(set(t.split()) & title_tokens) >= 2]
        pts = 15 if want_hit else (10 if past_ids else 3)
        expl = (
            "Matches a job title you're looking for."
            if want_hit
            else "Similar to roles you've held."
            if past_ids
            else "Different from your target and past titles."
        )
        factors.append(Factor("Role fit", 15, pts, expl, past_ids))

    # --- Practicalities (5) + eligibility blockers
    pts = 5.0
    if opp.closes_at and opp.closes_at < today:
        eligible = False
        pts = 0
        gaps.append(
            Gap(
                "deadline_passed",
                "blocker",
                f"The deadline ({opp.closes_at.isoformat()}) has passed.",
            )
        )
    elif opp.closes_at and (opp.closes_at - today).days <= 14:
        gaps.append(
            Gap(
                "deadline_soon",
                "info",
                f"Deadline in {(opp.closes_at - today).days} days ({opp.closes_at.isoformat()}).",
            )
        )
    sig = read_signals(opp.description)
    sponsorship = opp.sponsorship
    if sponsorship is Sponsorship.UNKNOWN and sig.sponsorship != "not_stated":
        sponsorship = Sponsorship.YES if sig.sponsorship == "offered" else Sponsorship.NO
    if prefs.needs_visa_sponsorship and sponsorship is Sponsorship.NO:
        pts = 0
        gaps.append(
            Gap(
                "no_sponsorship",
                "blocker",
                "The posting says it doesn't offer visa sponsorship, which you need"
                + (f' ("{sig.quotes["sponsorship"]}").' if "sponsorship" in sig.quotes else "."),
            )
        )
        eligible = False  # flexible mode stretches experience, never visa rules
    elif prefs.needs_visa_sponsorship and sponsorship is Sponsorship.UNKNOWN:
        gaps.append(
            Gap(
                "sponsorship_unknown",
                "info",
                "Visa sponsorship isn't mentioned. Check before applying.",
            )
        )
    strict = mode is ExperienceMode.STRICT
    authorized_here = bool(geo.countries) and all(
        c in cand.work_authorization for c in geo.countries
    )
    if sig.authorization_required and not authorized_here:
        pts = 0
        gaps.append(
            Gap(
                "work_authorization",
                "blocker" if strict else "gap",
                f'Requires an existing right to work there ("{sig.quotes["authorization"]}").',
            )
        )
        if strict:
            eligible = False
    # Languages are a hard requirement, not a stretch: flexible mode widens experience only.
    # Checked only once the person has listed the languages they work in.
    written = req.language
    needed = list(sig.languages_required)
    if written and written != "en" and written not in needed:
        needed.append(written)
    for lang in needed:
        if lang in prefs.languages:
            continue
        name = LANGUAGE_NAMES.get(lang, lang)
        why = (
            f'Asks for {name} ("{sig.quotes[f"language:{lang}"]}")'
            if f"language:{lang}" in sig.quotes
            else f"Written in {name}, so the job most likely needs {name}"
        )
        if not prefs.languages:
            gaps.append(
                Gap(
                    f"language_{lang}",
                    "info",
                    f"{why}. Add the languages you work in (Preferences) to check this.",
                )
            )
            continue
        eligible = False
        gaps.append(
            Gap(
                f"language_{lang}",
                "blocker",
                f"{why}, which isn't in your languages. Add it to your languages if you can "
                "work in it.",
            )
        )
    funding = prefs.funding if not prefs.funding_required else "required"
    if opp.kind in ACADEMIC_KINDS and funding != "any":
        if sig.funding == "unfunded":
            gaps.append(
                Gap(
                    "unfunded",
                    "blocker" if funding == "required" else "gap",
                    f'Not funded ("{sig.quotes["funding"]}").',
                )
            )
            if funding == "required":
                eligible = False
        elif sig.funding == "not_stated" and not opp.funding:
            gaps.append(
                Gap("funding_unknown", "info", "Funding isn't described for this position.")
            )
    if prefs.max_upfront_cost is not None and prefs.budget_currency:
        total, unconverted = 0.0, []
        for fee in sig.fees:
            v = fx_convert(fee.amount, fee.currency, prefs.budget_currency, cand.fx_rates)
            if v is None:
                unconverted.append(fee.currency)
            else:
                total += v
        if total > prefs.max_upfront_cost:
            eligible = False
            gaps.append(
                Gap(
                    "over_budget",
                    "blocker",
                    f"Stated fees are about {total:,.0f} {prefs.budget_currency}, above "
                    f"your budget of {prefs.max_upfront_cost:,} {prefs.budget_currency}.",
                )
            )
        elif unconverted:
            gaps.append(
                Gap(
                    "cost_unconverted",
                    "info",
                    f"Fees in {', '.join(sorted(set(unconverted)))} couldn't be converted; check.",
                )
            )
        elif not sig.fees and opp.kind in ACADEMIC_KINDS and sig.funding != "funded":
            gaps.append(
                Gap(
                    "cost_not_stated",
                    "info",
                    "Costs and fees aren't stated; check them against your budget before applying.",
                )
            )
    factors.append(
        Factor(
            "Practicalities",
            5,
            pts,
            "Deadline, sponsorship, work rights, language, funding and cost checks.",
        )
    )

    score = round(sum(f.points for f in factors))
    return MatchResult(
        score=max(0, min(100, score)),
        eligible=eligible,
        mode=mode.value,
        factors=factors,
        gaps=gaps,
    )


def is_job_kind(kind: OpportunityKind) -> bool:
    return kind is OpportunityKind.JOB
