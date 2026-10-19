"""Requirements read from posting text, and how matching uses them (found in the M17 real run:
real postings have no structured skills or experience fields, so every match scored the same)."""

from datetime import date

from nexscout.domain.matching import CandidateSummary, Experience, match
from nexscout.domain.mindmap import normalize_org
from nexscout.domain.opportunities import NormalizedOpportunity, OpportunityKind
from nexscout.domain.preferences import ExperienceMode, Preferences
from nexscout.domain.requirements import min_years, read_requirements, skills_in, written_in

TODAY = date(2026, 10, 19)
EN = (
    "You will build and ship machine learning systems with our team. We are looking for an "
    "engineer who is curious and kind, and who will help us grow. You have experience with the "
    "tools below and you are able to work on your own as well as with others in our office. "
)
SV = (
    "Vi söker en utvecklare som vill arbeta med maskininlärning och som har erfarenhet av att "
    "bygga system. Du är en del av vårt team och har en god förmåga att samarbeta med andra "
    "inom och utanför företaget. Hos oss får du arbeta med spännande uppdrag och vi är ett "
    "team som har kul tillsammans och som för det mesta arbetar på plats hos våra kunder. "
)


def test_skills_found_by_any_spelling_and_not_in_ordinary_words() -> None:
    text = "Experience with PyTorch, scikit-learn, LLMs and RAG; k8s and Docker a plus."
    assert skills_in(text) == ["PyTorch", "scikit-learn", "LLMs", "RAG", "Kubernetes", "Docker"]
    assert skills_in("Spark curiosity and a swift response; go the extra mile.") == []
    assert skills_in("We use Weaviate and Polars.", extra=["Polars"]) == [
        "Vector databases",
        "Polars",
    ]


def test_years_seniority_language_and_doctorate() -> None:
    assert min_years("At least 3-5 years of professional experience")[0] == 3
    assert min_years("Founded 12 years ago. 2+ years of experience with Python.")[0] == 2
    assert min_years("mindestens 4 Jahre Berufserfahrung")[0] == 4
    assert min_years("We have offices in 4 countries.") == (None, None)
    assert read_requirements("Senior ML Engineer", None).seniority == "senior"
    assert read_requirements("(Senior) ML Engineer (m/w/d)", None).seniority is None
    assert read_requirements("Junior Data Scientist", None).seniority == "junior"
    assert read_requirements("Postdoctoral researcher in vision", None).needs_doctorate
    assert written_in(EN * 2) == "en"
    assert written_in(SV * 2) == "sv"
    assert written_in("Too short to say.") is None


def _opp(**kw: object) -> NormalizedOpportunity:
    base: dict[str, object] = {
        "source_key": "t",
        "external_id": "1",
        "source_url": "https://x.example/1",
        "kind": OpportunityKind.JOB,
        "title": "Machine Learning Engineer",
        "organization_name": "Acme",
        "country_codes": ["SE"],
    }
    base.update(kw)
    return NormalizedOpportunity(**base)  # type: ignore[arg-type]


def _cand(**prefs: object) -> CandidateSummary:
    return CandidateSummary(
        skills={"python": "f1", "pytorch": "f2", "llm fine-tuning": "f3"},
        employment=[Experience("f4", "ML Engineer", "2023-01", "present")],
        degrees=[("master", "f5")],
        preferences=Preferences(**{"experience_mode": ExperienceMode.FLEXIBLE, **prefs}),  # type: ignore[arg-type]
    )


def test_skills_from_text_rank_postings_apart() -> None:
    cand = _cand()
    close = match(_opp(description=EN + "Python, PyTorch and LoRA fine-tuning."), cand, TODAY)
    far = match(_opp(description=EN + "Java, Kotlin, Spring and Kubernetes."), cand, TODAY)
    skills = next(f for f in close.factors if f.name == "Skills")
    assert "you list 3" in skills.explanation
    assert set(skills.fact_ids) == {"f1", "f2", "f3"}  # "LoRA" meets "LLM fine-tuning"
    assert close.score > far.score
    assert "missing_skills" in {g.code for g in far.gaps}


def test_experience_and_seniority_from_text() -> None:
    cand = _cand()  # about 3.8 years
    out = match(_opp(description=EN + "You bring 6+ years of experience."), cand, TODAY)
    gap = next(g for g in out.gaps if g.code == "experience_below_minimum")
    assert "6+ years" in gap.message
    assert "6+ years of experience" in gap.message  # quotes the posting
    senior = match(_opp(title="Senior ML Engineer", description=EN), cand, TODAY)
    assert "senior_title" in {g.code for g in senior.gaps}
    assert senior.eligible  # a stretch, not a blocker


def test_visa_and_language_rules_hold_in_flexible_mode() -> None:
    cand = _cand(needs_visa_sponsorship=True, languages=["en"])
    refused = match(_opp(description=EN + "We do not sponsor visas."), cand, TODAY)
    assert not refused.eligible
    assert {g.severity for g in refused.gaps if g.code == "no_sponsorship"} == {"blocker"}
    swedish = match(_opp(description=SV * 2), cand, TODAY)
    assert not swedish.eligible
    assert "Written in Swedish" in next(g.message for g in swedish.gaps if g.code == "language_sv")
    # Languages not filled in yet: a note, never a silent block.
    unknown = match(_opp(description=SV * 2), _cand(), TODAY)
    assert unknown.eligible
    assert {g.severity for g in unknown.gaps if g.code == "language_sv"} == {"info"}


def test_postdoc_needs_a_doctorate() -> None:
    out = match(
        _opp(kind=OpportunityKind.POSTDOC, title="Postdoc in computer vision"), _cand(), TODAY
    )
    assert not out.eligible
    assert "doctorate_required" in {g.code for g in out.gaps}


def test_university_names_in_any_language_are_one_employer() -> None:
    assert normalize_org("Lunds universitet") == normalize_org("Lund University")
    assert normalize_org("Spotify AB") == normalize_org("Spotify")
    assert normalize_org("Wolt Oy") == "wolt"


def test_a_language_that_is_a_plus_is_not_required() -> None:
    from nexscout.domain.research import extract_findings
    from nexscout.domain.signals import read_signals

    assert read_signals("Fluent German is a plus but not required.").languages_required == []
    assert read_signals("Sehr gute Deutschkenntnisse sind von Vorteil.").languages_required == []
    assert read_signals("Fluent Finnish is required. A licence is a plus.").languages_required == [
        "fi"
    ]
    found = {
        (f.field, f.summary)
        for f in extract_findings(
            "You have 3+ years of experience with PyTorch. We offer visa sponsorship and a "
            "relocation package. Fluent German is a plus but not required."
        )
    }
    assert found == {
        ("experience", "Asks for 3+ years"),
        ("visa", "Visa support offered"),
        ("relocation", "Relocation support"),
    }
