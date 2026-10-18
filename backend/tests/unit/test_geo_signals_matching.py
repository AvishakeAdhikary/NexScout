"""M15: countries (ISO codes, groups), eligibility signals, FX and the matching rules using them."""

from datetime import date

import pytest

from nexscout.domain.fx import convert
from nexscout.domain.geo import countries, expand, groups, in_area, normalize_list, resolve_location
from nexscout.domain.matching import CandidateSummary, match
from nexscout.domain.opportunities import NormalizedOpportunity, OpportunityKind
from nexscout.domain.preferences import Preferences
from nexscout.domain.signals import read_signals

TODAY = date(2026, 10, 19)


def test_every_iso_country_and_the_common_groups_exist() -> None:
    assert len(countries()) == 249
    assert {"FI", "SE", "DE", "IN", "US", "GB", "CH"} <= set(countries())
    assert len(expand(["EU"])) == 27
    assert expand(["NORDICS"]) == {"DK", "FI", "IS", "NO", "SE"}
    assert {"CH", "GB", "NO", "FI"} <= expand(["EUROPE"])
    assert "IN" not in expand(["EUROPE"])
    assert set(groups()) >= {"EU", "EEA", "SCHENGEN", "EUROPE", "NORDICS", "DACH", "ASIA"}


@pytest.mark.parametrize(
    ("text", "codes", "remote", "scope"),
    [
        ("Espoo, Finland", ["FI"], False, None),
        ("München", ["DE"], False, None),
        ("Belfast, Northern Ireland", ["GB"], False, None),
        ("London, UK or Dublin", ["GB", "IE"], False, None),
        ("Remote - EU", [], True, "EU"),
        ("Remote (Worldwide)", [], True, "WORLD"),
        ("Helsinki · Remote", ["FI"], True, "FI"),
        ("Zurich, CH", ["CH"], False, None),
        ("Jyväskylä", ["FI"], False, None),
        ("Bengaluru", ["IN"], False, None),
        ("Somewhere nice", [], False, None),
        ("", [], False, None),
    ],
)
def test_resolve_location(text: str, codes: list[str], remote: bool, scope: str | None) -> None:
    r = resolve_location(text)
    assert (r.countries, r.remote, r.remote_scope) == (codes, remote, scope)


def test_area_checks_and_user_input() -> None:
    eu = expand(["EU"])
    assert in_area(resolve_location("Berlin"), eu) is True
    assert in_area(resolve_location("Bengaluru"), eu) is False
    assert in_area(resolve_location("Remote - EU"), eu) is True
    assert in_area(resolve_location("Remote (worldwide)"), eu) is True
    assert in_area(resolve_location("Nowhere"), eu) is None  # unknown is never a guess
    assert normalize_list(["Finland", "eu", "DE", "Atlantis"]) == (["FI", "EU", "DE"], ["Atlantis"])


def test_signals_from_posting_text() -> None:
    s = read_signals(
        "We offer visa sponsorship and a relocation package. Fluent Finnish is "
        "required. Application fee: EUR 100. Tuition fee 1.500 € per year."
    )
    assert s.sponsorship == "offered"
    assert s.relocation
    assert s.languages_required == ["fi"]
    assert [(f.kind, f.amount, f.currency) for f in s.fees] == [
        ("application_fee", 100.0, "EUR"),
        ("tuition", 1500.0, "EUR"),
    ]
    refused = read_signals("We are unable to sponsor visas. Must have EU work authorization.")
    assert refused.sponsorship == "refused"
    assert refused.authorization_required
    assert read_signals("Fully funded doctoral researcher position").funding == "funded"
    assert read_signals("This is a self-funded PhD").funding == "unfunded"
    nothing = read_signals("")
    assert (nothing.sponsorship, nothing.funding, nothing.fees) == ("not_stated", "not_stated", [])


def test_fx_conversion() -> None:
    rates = {"INR": 106.864, "USD": 1.08}
    assert convert(100, "EUR", "INR", rates) == pytest.approx(10686.4)
    assert convert(10686.4, "INR", "EUR", rates) == pytest.approx(100)
    assert convert(5, "GBP", "INR", rates) is None  # no rate: no guess


def _opp(**kw: object) -> NormalizedOpportunity:
    base: dict[str, object] = {
        "source_key": "t",
        "external_id": "1",
        "source_url": "https://x.example/1",
        "kind": OpportunityKind.JOB,
        "title": "Machine Learning Engineer",
        "organization_name": "Acme",
    }
    base.update(kw)
    return NormalizedOpportunity(**base)  # type: ignore[arg-type]


def _cand(**prefs: object) -> CandidateSummary:
    return CandidateSummary(preferences=Preferences(**prefs), fx_rates={"INR": 106.864})  # type: ignore[arg-type]


def _codes(result: object) -> set[str]:
    return {g.code for g in result.gaps}  # type: ignore[attr-defined]


def test_country_include_and_exclude() -> None:
    cand = _cand(countries=["EUROPE"], countries_exclude=["GB"])
    assert match(_opp(country_codes=["FI"]), cand, TODAY).eligible
    out = match(_opp(country_codes=["IN"]), cand, TODAY)
    assert not out.eligible
    assert "outside_countries" in _codes(out)
    excluded = match(_opp(country_codes=["GB"]), cand, TODAY)
    assert not excluded.eligible
    assert "excluded_country" in _codes(excluded)
    unknown = match(_opp(location_text="Somewhere"), cand, TODAY)
    assert unknown.eligible
    assert "location_unknown" in _codes(unknown)


def test_visa_language_funding_and_budget_rules() -> None:
    cand = _cand(
        needs_visa_sponsorship=True,
        languages=["en"],
        funding="required",
        max_upfront_cost=150_000,
        budget_currency="INR",
    )
    refused = match(_opp(description="Unfortunately we cannot sponsor visas."), cand, TODAY)
    assert "no_sponsorship" in _codes(refused) or "work_authorization" in _codes(refused)
    finnish = match(_opp(description="Fluent Finnish is required."), cand, TODAY)
    assert not finnish.eligible
    assert "language_fi" in _codes(finnish)
    phd = {"kind": OpportunityKind.PHD, "title": "Doctoral researcher in computer vision"}
    unfunded = match(_opp(**phd, description="This is a self-funded position."), cand, TODAY)
    assert not unfunded.eligible
    assert "unfunded" in _codes(unfunded)
    pricey = match(_opp(**phd, description="Fully funded. Application fee: EUR 2000."), cand, TODAY)
    assert not pricey.eligible  # 2000 EUR ≈ 213,728 INR > 150,000 INR
    assert "over_budget" in _codes(pricey)
    cheap = match(_opp(**phd, description="Fully funded. Application fee: EUR 100."), cand, TODAY)
    assert cheap.eligible
    silent = match(_opp(**phd, description="A doctoral position in vision."), cand, TODAY)
    assert {"funding_unknown", "cost_not_stated"} <= _codes(silent)
