"""Form planning: only known values, declarations deferred, blockers detected, plan fingerprint."""

from nexscout.domain.forms import (
    Applicant,
    FormField,
    detect_blocker,
    detect_confirmation,
    normalize_question,
    plan_form,
)
from nexscout.infrastructure.browser import Guard

FIELDS = [
    FormField("#full_name", "Full name *", "text", True, "full_name"),
    FormField("#email", "Email address *", "email", True, "email"),
    FormField("#phone", "Phone", "tel", False, "phone"),
    FormField("#motivation", "Why are you interested in this role? *", "textarea", True),
    FormField("#cv", "CV / résumé (PDF) *", "file", True),
    FormField("#cover_letter", "Cover letter (PDF)", "file", False),
    FormField("#newsletter", "Send me job alerts", "checkbox", False),
    FormField(
        "#declaration", "I confirm that the information is accurate and complete.", "checkbox", True
    ),
    FormField("#csrf", "", "hidden", False),
]
ME = Applicant(
    full_name="Ada Example",
    email="ada@example.com",
    files={"cv": {"path": "/work/run-1/cv.pdf", "title": "Resume (v1, PDF)"}},
)


def test_missing_required_answers_stop_the_plan() -> None:
    plan = plan_form(FIELDS, ME)
    assert plan.missing == ["Why are you interested in this role? *"]


def test_plan_uses_only_known_values_and_defers_declarations() -> None:
    who = Applicant(
        **{
            **ME.__dict__,
            "answers": {
                normalize_question("Why are you interested in this role? *"): "I like ML platforms."
            },
        }
    )
    plan = plan_form(FIELDS, who)
    assert plan.missing == []
    by = {f.key: f for f in plan.fields}
    assert (by["#full_name"].action, by["#full_name"].value) == ("fill", "Ada Example")
    assert by["#email"].value == "ada@example.com"
    assert by["#phone"].action == "skip"  # no phone given: nothing invented
    assert by["#motivation"].source == "your answer"
    assert (by["#cv"].action, by["#cv"].source) == ("upload", "Resume (v1, PDF)")
    assert by["#cover_letter"].action == "skip"
    assert by["#newsletter"].action == "skip"  # never opt the user in
    assert by["#declaration"].action == "check_on_submit"
    assert plan.attestations == ["I confirm that the information is accurate and complete."]
    assert "#csrf" not in by
    assert all("/work/" not in str(r["value"]) for r in plan.summary())  # no paths shown


def test_digest_tracks_what_will_be_entered() -> None:
    answers = {normalize_question("Why are you interested in this role?"): "A"}
    a = plan_form(FIELDS, Applicant(**{**ME.__dict__, "answers": answers}))
    moved = Applicant(
        **{
            **ME.__dict__,
            "answers": answers,
            "files": {"cv": {"path": "/other/cv.pdf", "title": "Resume (v1, PDF)"}},
        }
    )
    assert plan_form(FIELDS, moved).digest() == a.digest()  # temp paths don't matter
    changed = Applicant(
        **{
            **ME.__dict__,
            "answers": {normalize_question("Why are you interested in this role?"): "B"},
        }
    )
    assert plan_form(FIELDS, changed).digest() != a.digest()
    extra = [*FIELDS, FormField("#salary", "Expected salary *", "text", True)]
    assert plan_form(extra, Applicant(**{**ME.__dict__, "answers": answers})).missing == [
        "Expected salary *"
    ]


def test_blockers_and_confirmation() -> None:
    assert detect_blocker("Please verify you are human", False, False) == "captcha"
    assert detect_blocker("Welcome", False, True) == "captcha"
    assert detect_blocker("Sign in", True, False) == "login"
    assert detect_blocker("Apply now", False, False) is None
    assert detect_confirmation("Thank you for applying. Reference: FX-1001") == (True, "FX-1001")
    assert detect_confirmation("We are processing your request.") == (False, None)
    assert detect_confirmation("Reference: AB-12 but nothing else") == (False, None)


def test_guard_blocks_private_networks_but_allows_the_demo_site() -> None:
    g = Guard(frozenset({"http://127.0.0.1:8100"}))
    assert g.allows("http://127.0.0.1:8100/fixture-site/apply/x")
    assert not g.allows("http://127.0.0.1:5432/")
    assert not g.allows("http://169.254.169.254/latest/meta-data")
    assert not g.allows("http://10.0.0.5/admin")
    assert not g.allows("file:///etc/passwd")
    assert g.allows("data:image/png;base64,AAAA")


def test_contact_details_fill_name_parts_location_and_links() -> None:
    fields = [
        FormField("#first", "First name *", "text", True),
        FormField("#last", "Last name *", "text", True),
        FormField("#city", "City", "text", False),
        FormField("#country", "Country of residence *", "text", True),
        FormField("#citizen", "Country of citizenship", "text", False),
        FormField("#where", "Current location", "text", False),
        FormField("#zip", "Postal code", "text", False),
        FormField("#li", "LinkedIn profile", "url", False),
        FormField("#ref_phone", "Referee phone number", "tel", False),
    ]
    who = Applicant(
        **{
            **ME.__dict__,
            "given_name": "Ada",
            "family_name": "Example",
            "city": "Pune",
            "country": "India",
            "location": "Pune, India",
            "phone": "+91 00000 00000",
            "links": {"linkedin": "https://www.linkedin.com/in/ada-example"},
        }
    )
    plan = plan_form(fields, who)
    by = {f.key: (f.action, f.value) for f in plan.fields}
    assert by["#first"] == ("fill", "Ada")
    assert by["#last"] == ("fill", "Example")
    assert by["#city"] == ("fill", "Pune")
    assert by["#country"] == ("fill", "India")
    assert by["#where"] == ("fill", "Pune, India")
    assert by["#li"] == ("fill", "https://www.linkedin.com/in/ada-example")
    assert by["#zip"] == ("skip", None)  # not given: nothing invented
    # Citizenship is not where you live, and a referee's phone isn't yours.
    assert by["#citizen"] == ("skip", None)
    assert by["#ref_phone"] == ("skip", None)
    assert plan.missing == []


def test_a_required_contact_detail_that_was_never_given_stops_the_plan() -> None:
    plan = plan_form([FormField("#city", "City *", "text", True)], ME)
    assert plan.missing == ["City *"]
