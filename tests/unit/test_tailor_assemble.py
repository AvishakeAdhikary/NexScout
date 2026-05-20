"""assemble_resume_text — code, not the LLM, owns the header layout."""

from __future__ import annotations

from nexscout.core.profile import Profile
from nexscout.scoring.tailor import assemble_resume_text, build_system_prompt, build_user_payload


def _profile() -> Profile:
    return Profile.model_validate({
        "me": {
            "legal": "Jane Q. Public",
            "pref": "Jane",
            "email": "jane@example.com",
            "phone": "+1-415-555-0100",
            "links": {"li": "linkedin.com/in/jane", "gh": "github.com/jane"},
        },
        "facts": {
            "companies": ["Acme Corp", "Globex"],
            "school": "State University",
            "metrics": ["10M MAU"],
        },
        "skills": {
            "lang": ["Python", "Go"],
            "fw": ["FastAPI"],
            "infra": ["Docker"],
            "data": ["Postgres"],
            "tools": ["Git"],
        },
        "exp": {"edu": "BSc Computer Science"},
    })


_TAILOR_JSON = {
    "title": "Staff Engineer",
    "summary": "Senior engineer with deep backend experience.",
    "skills": {
        "Languages": "Python, Go",
        "Frameworks": "FastAPI",
        "Infra": "Docker, Kubernetes",
    },
    "experience": [
        {
            "header": "Senior Engineer at Acme Corp",
            "subtitle": "Python | 2020-2024",
            "bullets": ["Built X", "Shipped Y"],
        },
        {"header": "Engineer at Globex", "subtitle": "Go | 2018-2020", "bullets": ["Did Z"]},
    ],
    "projects": [
        {"header": "Search Indexer", "subtitle": "Python | 2023", "bullets": ["50M docs/day"]},
    ],
    "education": "State University | BSc Computer Science",
}


def test_assembled_resume_has_required_sections() -> None:
    profile = _profile()
    text = assemble_resume_text(_TAILOR_JSON, profile)
    for section in ("SUMMARY", "TECHNICAL SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"):
        assert section in text


def test_assembled_resume_has_header_from_profile_not_llm() -> None:
    profile = _profile()
    text = assemble_resume_text(_TAILOR_JSON, profile)
    # Header line is the legal name, not anything the LLM provided.
    first_line = text.splitlines()[0]
    assert first_line == "Jane Q. Public"
    # Email/phone come from profile.
    assert "jane@example.com" in text
    assert "+1-415-555-0100" in text


def test_assembled_resume_preserves_companies_and_school() -> None:
    profile = _profile()
    text = assemble_resume_text(_TAILOR_JSON, profile)
    assert "Acme Corp" in text
    assert "Globex" in text
    assert "State University" in text


def test_assembled_resume_sanitises_smart_quotes_and_dashes() -> None:
    profile = _profile()
    data = dict(_TAILOR_JSON)
    data["summary"] = "Built “the search indexer” — fast and reliable."
    text = assemble_resume_text(data, profile)
    assert "—" not in text
    assert "“" not in text


def test_system_prompt_includes_profile_skills() -> None:
    profile = _profile()
    prompt = build_system_prompt(profile)
    assert "Python, Go" in prompt
    assert "Acme Corp, Globex" in prompt
    assert "State University" in prompt
    # Required banned words appear in the prompt.
    assert "passionate" in prompt
    assert "spearheaded" in prompt


def test_user_payload_truncates_long_descriptions() -> None:
    profile = _profile()
    job = {"title": "T", "site": "S", "location": "L", "full_description": "X" * 10_000}
    payload = build_user_payload(profile, job)
    assert "X" * 6000 in payload
    assert "X" * 6001 not in payload
