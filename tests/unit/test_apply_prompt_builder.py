"""build_prompt — substitutions filled, byte-equality with §13.4 template."""

from __future__ import annotations

from nexscout.apply.prompt import SYSTEM_PROMPT_TEMPLATE, build_prompt
from nexscout.core.profile import Profile


def _fixed_profile() -> Profile:
    return Profile.model_validate(
        {
            "me": {
                "legal": "Jane Q. Public",
                "pref": "Jane",
                "email": "jane@example.com",
                "phone": "+1-415-555-0100",
                "city": "San Francisco",
                "region": "CA",
                "country": "USA",
                "postcode": "94110",
                "address": "123 Main St",
                "links": {
                    "li": "linkedin.com/in/janepublic",
                    "gh": "github.com/janepublic",
                    "web": "jane.dev",
                    "portfolio": "jane.dev/work",
                },
            },
            "auth": {"authorized": True, "sponsor": False, "permit": "USC"},
            "pay": {"expect": 165000, "range": [150000, 200000], "currency": "USD"},
            "avail": {"start": "Immediately"},
            "exp": {
                "years": 7,
                "edu": "BSc Computer Science",
                "current_title": "Senior Software Engineer",
                "target_titles": ["Staff Engineer"],
            },
            "eeo": {"gender": "decline", "race": "decline", "veteran": "not-protected", "disability": "decline"},
            "search": {"locations": [{"label": "Bay Area", "q": "San Francisco, CA"}], "min_score": 7},
            "captcha": {"api_key": "x"},
            "password": "secret",
        }
    )


def _fixed_job() -> dict[str, object]:
    return {
        "url": "https://example.com/apply/123",
        "application_url": "https://example.com/apply/123",
        "title": "Staff Engineer",
        "site": "ExampleCo",
        "fit_score": 9,
    }


def test_build_prompt_is_byte_equal_to_template_for_fixed_input() -> None:
    """Pinning the inputs gives a deterministic, byte-equal output to the §13.4 template."""
    profile = _fixed_profile()
    job = _fixed_job()

    out = build_prompt(
        job=job,
        tailored_resume="JANE Q. PUBLIC\nStaff Engineer\njane@example.com",
        cover_letter="Dear Hiring Manager,\nI built things.\nJane",
        dry_run=False,
        profile=profile,
        bundle_dir="/var/data/applications/000123",
        today_iso="2026-05-21",
    )

    expected = SYSTEM_PROMPT_TEMPLATE.format(
        job_url="https://example.com/apply/123",
        title="Staff Engineer",
        site="ExampleCo",
        fit_score=9,
        bundle_dir="/var/data/applications/000123",
        tailored_resume_text="JANE Q. PUBLIC\nStaff Engineer\njane@example.com",
        cover_letter_text="Dear Hiring Manager,\nI built things.\nJane",
        legal_name="Jane Q. Public",
        pref_name="Jane",
        last_name="Public",
        email="jane@example.com",
        password="secret",
        phone="+1-415-555-0100",
        phone_digits="14155550100",
        address="123 Main St",
        city="San Francisco",
        region="CA",
        country="USA",
        postcode="94110",
        linkedin="linkedin.com/in/janepublic",
        github="github.com/janepublic",
        portfolio="jane.dev/work",
        website="jane.dev",
        work_auth="Yes",
        sponsor="No",
        permit="USC",
        salary_expect=165000,
        salary_low=150000,
        salary_high=200000,
        currency="USD",
        years=7,
        education="BSc Computer Science",
        available="Immediately",
        eeo_gender="decline",
        eeo_race="decline",
        eeo_veteran="not-protected",
        eeo_disability="decline",
        auth_rule="USC. Sponsorship needed: No.",
        accept_cities="San Francisco, Bay Area",
        target_title="Staff Engineer",
        display_name="Jane",
        today_us="05/21/2026",
    )

    assert out == expected


def test_build_prompt_substitutes_profile_fields() -> None:
    profile = _fixed_profile()
    out = build_prompt(
        job=_fixed_job(),
        tailored_resume="...",
        cover_letter=None,
        dry_run=False,
        profile=profile,
    )
    assert "Name: Jane Q. Public" in out
    assert "Email: jane@example.com" in out
    assert "Sponsorship Needed: No" in out
    assert "$165000 USD is the FLOOR" in out
    # Verbatim §13.4 path + the literal " or N/A" hint from the template.
    assert "cover_letter.pdf or N/A" in out


def test_auth_rule_with_sponsor() -> None:
    p = Profile.model_validate(
        {
            "me": {"legal": "X", "pref": "X", "email": "x@y.z", "phone": "1"},
            "auth": {"authorized": False, "sponsor": True, "permit": "H1B"},
            "captcha": {"api_key": "x"},
        }
    )
    out = build_prompt(
        job=_fixed_job(),
        tailored_resume="",
        cover_letter=None,
        dry_run=False,
        profile=p,
    )
    assert "H1B. Sponsorship needed: Yes." in out


def test_cover_letter_placeholder_when_missing() -> None:
    p = _fixed_profile()
    out = build_prompt(
        job=_fixed_job(),
        tailored_resume="",
        cover_letter=None,
        dry_run=False,
        profile=p,
    )
    assert "None available." in out
    assert "based in San Francisco" in out
