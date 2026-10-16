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
    work_authorization: list[str] = field(default_factory=list)  # only if user opted in


def summarize(
    facts: list[tuple[str, Section, dict[str, Any]]], preferences: Preferences
) -> CandidateSummary:
    """Build the matcher input from *accepted* facts only."""
    s = CandidateSummary(preferences=preferences)
    if preferences.sensitive.use_for_eligibility:
        s.work_authorization = [c.lower() for c in preferences.sensitive.work_authorization]
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


def match(opp: NormalizedOpportunity, cand: CandidateSummary, today: date) -> MatchResult:
    prefs = cand.preferences
    mode = prefs.experience_mode
    factors: list[Factor] = []
    gaps: list[Gap] = []
    eligible = True
    skills_by_norm = {_norm_skill(k): fid for k, fid in cand.skills.items()}

    # --- Skills (35)
    required = [s for s in opp.required_skills if s.strip()]
    if required:
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
    exp_ids = [e.fact_id for e in exp_entries]
    if need is None:
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
                f"About {years:g} years of experience; {need:g}+ requested.",
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
                    f"Asks for {need:g}+ years; you have about {years:g}.{note} Hidden "
                    "in strict mode. Switch to flexible mode to see stretch roles.",
                )
            )
        else:
            gaps.append(
                Gap(
                    "experience_below_minimum",
                    "gap",
                    f"Stretch role: asks for {need:g}+ years, you have about {years:g} "
                    f"({short:g} short).{note}",
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
    req_level = (opp.education_level or "").lower() or None
    if req_level and req_level in DEGREE_LEVELS:
        if best >= DEGREE_LEVELS[req_level]:
            factors.append(
                Factor("Education", 10, 10, f"Meets the {req_level} requirement.", best_ids)
            )
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

    # --- Location (15)
    countries = {c.lower() for c in prefs.countries}
    cities = {c.lower() for c in prefs.cities}
    opp_country = (opp.location_country or "").lower()
    opp_city = (opp.location_city or "").lower()
    if opp.remote is Remote.REMOTE and prefs.remote in ("any", "remote", "hybrid"):
        factors.append(Factor("Location", 15, 15, "Remote role."))
    elif not countries and not cities:
        factors.append(Factor("Location", 15, 15, "You haven't set location preferences."))
    elif (opp_city and opp_city in cities) or (opp_country and opp_country in countries):
        where = opp.location_city or opp.location_country
        factors.append(Factor("Location", 15, 15, f"{where} is in your preferred locations."))
    else:
        where = ", ".join(x for x in (opp.location_city, opp.location_country) if x) or "unknown"
        factors.append(Factor("Location", 15, 0, f"Location ({where}) isn't in your preferences."))
        gaps.append(
            Gap(
                "location_outside_preferences",
                "info",
                f"Located in {where}, outside your preferred locations.",
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
    if prefs.needs_visa_sponsorship and opp.sponsorship is Sponsorship.NO:
        pts = 0
        gaps.append(
            Gap(
                "no_sponsorship",
                "blocker" if mode is ExperienceMode.STRICT else "gap",
                "The posting says it doesn't offer visa sponsorship, which you need.",
            )
        )
        if mode is ExperienceMode.STRICT:
            eligible = False
    elif prefs.needs_visa_sponsorship and opp.sponsorship is Sponsorship.UNKNOWN:
        gaps.append(
            Gap(
                "sponsorship_unknown",
                "info",
                "Visa sponsorship isn't mentioned. Check before applying.",
            )
        )
    if prefs.funding_required and opp.kind in ACADEMIC_KINDS and not opp.funding:
        gaps.append(Gap("funding_unknown", "info", "Funding isn't described for this position."))
    if (
        cand.work_authorization
        and opp_country
        and opp.sponsorship is Sponsorship.NO
        and opp_country not in cand.work_authorization
    ):
        gaps.append(
            Gap(
                "work_authorization",
                "gap",
                "Requires existing work authorization in this country (based on the "
                "eligibility details you chose to share).",
            )
        )
    factors.append(Factor("Practicalities", 5, pts, "Deadline and sponsorship checks."))

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
