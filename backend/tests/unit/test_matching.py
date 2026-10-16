import dataclasses
from datetime import date

from nexscout.domain.matching import (
    CandidateSummary,
    Experience,
    match,
    summarize,
    years_of_experience,
)
from nexscout.domain.opportunities import NormalizedOpportunity
from nexscout.domain.preferences import Preferences
from nexscout.domain.profile import Section

TODAY = date(2026, 10, 16)


def opp(**kw: object) -> NormalizedOpportunity:
    base: dict[str, object] = {
        "source_key": "s",
        "external_id": "1",
        "source_url": "https://x.example/1",
        "kind": "job",
        "title": "Machine Learning Engineer",
        "organization_name": "Acme",
        "location_city": "Berlin",
        "location_country": "Germany",
        "required_skills": ["Python", "SQL", "Kubernetes"],
        "experience_min_years": 3,
        "education_level": "master",
        "closes_at": date(2026, 12, 1),
    }
    base.update(kw)
    return NormalizedOpportunity.model_validate(base)


def candidate(prefs: Preferences | None = None) -> CandidateSummary:
    facts = [
        ("s1", Section.SKILL, {"name": "Python"}),
        ("s2", Section.SKILL, {"name": "sql"}),
        (
            "e1",
            Section.EMPLOYMENT,
            {"title": "ML Engineer", "organization": "X", "start": "2021-01", "end": "present"},
        ),
        ("d1", Section.EDUCATION, {"institution": "Uni", "degree": "MSc"}),
    ]
    return summarize(facts, prefs or Preferences(countries=["Germany"]))


def test_years_of_experience_merges_overlaps() -> None:
    entries = [
        Experience("a", "x", "2020-01", "2020-12"),
        Experience("b", "y", "2020-06", "2021-05"),
    ]
    assert years_of_experience(entries, TODAY) == (1.4, True)
    assert years_of_experience([Experience("c", "z", None, None)], TODAY) == (0.0, False)


def test_explained_match_with_factors_gaps_and_evidence() -> None:
    r = match(opp(), candidate(), TODAY)
    assert r.eligible
    by = {f.name: f for f in r.factors}
    assert sum(f.weight for f in r.factors) == 100
    assert by["Skills"].fact_ids == ["s1", "s2"]
    assert "2 of 3" in by["Skills"].explanation
    assert by["Education"].points == 10
    assert by["Location"].points == 15
    assert any(g.code == "missing_skills" and "Kubernetes" in g.message for g in r.gaps)
    assert 0 < r.score <= 100


def test_strict_mode_hides_roles_above_experience() -> None:
    r = match(opp(experience_min_years=10), candidate(), TODAY)
    assert not r.eligible
    assert any(g.code == "experience_below_minimum" and g.severity == "blocker" for g in r.gaps)


def test_flexible_mode_shows_stretch_roles_with_disclosed_gap() -> None:
    prefs = Preferences(countries=["Germany"], experience_mode="flexible")
    r = match(opp(experience_min_years=10), candidate(prefs), TODAY)
    assert r.eligible
    gap = next(g for g in r.gaps if g.code == "experience_below_minimum")
    assert gap.severity == "gap"
    assert "short" in gap.message


def test_past_deadline_is_ineligible() -> None:
    r = match(opp(closes_at=date(2026, 1, 1)), candidate(), TODAY)
    assert not r.eligible
    assert any(g.code == "deadline_passed" for g in r.gaps)


def test_sponsorship_needed_but_not_offered() -> None:
    prefs = Preferences(countries=["Germany"], needs_visa_sponsorship=True)
    r = match(opp(sponsorship="no"), candidate(prefs), TODAY)
    assert not r.eligible
    assert any(g.code == "no_sponsorship" for g in r.gaps)


def test_matcher_input_has_no_protected_attributes() -> None:
    names = {f.name for f in dataclasses.fields(CandidateSummary)}
    forbidden = {
        "age",
        "gender",
        "race",
        "ethnicity",
        "religion",
        "disability",
        "veteran_status",
        "nationality",
        "marital_status",
        "sexual_orientation",
        "date_of_birth",
    }
    assert names.isdisjoint(forbidden)


def test_sensitive_attributes_ignored_without_opt_in() -> None:
    prefs = Preferences(sensitive={"work_authorization": ["Germany"], "veteran_status": "yes"})
    assert candidate(prefs).work_authorization == []
    prefs = Preferences(sensitive={"work_authorization": ["Germany"], "use_for_eligibility": True})
    assert candidate(prefs).work_authorization == ["germany"]


def test_scores_are_deterministic() -> None:
    assert match(opp(), candidate(), TODAY) == match(opp(), candidate(), TODAY)
