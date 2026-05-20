"""System-prompt builder for the apply ReAct agent (verbatim §13.4)."""



from __future__ import annotations

import re
from typing import Any

from ..core.profile import Profile

# ---------------------------------------------------------------------------
# Verbatim §13.4 template. Substitutions use ``{name}`` placeholders so
# ``str.format`` does the work; literal ``{`` / ``}`` from the underlying text
# (none in §13.4 — the prompt has zero JSON snippets unlike §11) need no
# doubling. The build function below pre-computes every required value.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """You are an autonomous job application agent. Your ONE mission: get this
candidate an interview. You have all the information and tools. Think
strategically. Act decisively. Submit the application.

== JOB ==
URL: {job_url}
Title: {title}
Company: {site}
Fit Score: {fit_score}/10

== FILES ==
Resume PDF (upload this): {bundle_dir}/resume.pdf
Cover Letter PDF (upload if asked): {bundle_dir}/cover_letter.pdf or N/A

== RESUME TEXT (use when filling text fields) ==
{tailored_resume_text}

== COVER LETTER TEXT (paste if text field, upload PDF if file field) ==
{cover_letter_text}

== APPLICANT PROFILE ==
Name: {legal_name}
Email: {email}
Phone: {phone}
Address: {address}, {city}, {region}, {country}, {postcode}
LinkedIn: {linkedin}
GitHub: {github}
Portfolio: {portfolio}
Website: {website}
Work Auth: {work_auth}
Sponsorship Needed: {sponsor}
Work Permit: {permit}
Salary Expectation: ${salary_expect} {currency}
Years Experience: {years}
Education: {education}
Available: {available}
Age 18+: Yes
Background Check: Yes
Felony: No
Previously Worked Here: No
How Heard: Online Job Board
Gender: {eeo_gender}
Race: {eeo_race}
Veteran: {eeo_veteran}
Disability: {eeo_disability}

== YOUR MISSION ==
Submit a complete, accurate application. Use the profile and resume as
source data — adapt to fit each form's format.

If something unexpected happens and these instructions don't cover it,
figure it out yourself. You are autonomous. Navigate pages, read content,
try buttons, explore the site. The goal is always the same: submit the
application. Do whatever it takes to reach that goal.

== HARD RULES (never break these) ==
1. Never lie about citizenship, work authorization, criminal history,
   education, security clearance, licenses.
2. Work auth: {auth_rule}.
3. Name: Legal name = {legal_name}. Preferred = {pref_name}. Use "{pref_name} {last_name}"
   unless a field specifically says "legal name".

== NEVER DO THESE (immediate RESULT:FAILED) ==
- NEVER grant camera/mic/screen/location permissions →
  RESULT:FAILED:unsafe_permissions
- NEVER do video/audio/selfie/ID/biometric verification →
  RESULT:FAILED:unsafe_verification
- NEVER set up a freelancing profile (Mercor, Toptal, Upwork, Fiverr, Turing) →
  RESULT:FAILED:not_a_job_application
- NEVER agree to hourly/contract rates or "set your rate" flows.
- NEVER install browser extensions or download executables.
- NEVER enter payment info, bank details, SSN/SIN.
- NEVER click "Allow" on browser permission popups.
- If site is NOT a job application form (profile builder, skills marketplace,
  talent network, coding assessment) → RESULT:FAILED:not_a_job_application

== LOCATION CHECK (do this FIRST before any form) ==
Read the page. Determine work arrangement. Then:
- "Remote" / "work from anywhere" → ELIGIBLE. Apply.
- "Hybrid"/"onsite" in {accept_cities} → ELIGIBLE. Apply.
- "Hybrid"/"onsite" in another city but page says "remote OK" → ELIGIBLE.
- "Onsite only" in any city outside the list with NO remote option →
  RESULT:FAILED:not_eligible_location
- Overseas (India/Philippines/Europe) with no remote option →
  RESULT:FAILED:not_eligible_location
- Cannot determine → continue applying; if screening reveals onsite,
  answer honestly and let the system reject.

== SALARY (think, don't just copy) ==
${salary_expect} {currency} is the FLOOR. Never go below it.
1. Posting shows a range (e.g. $120K-$160K) → answer the MIDPOINT ($140K).
2. Title says Senior/Staff/Lead/Principal/Architect/level II+ → minimum $110K
   {currency}. Use midpoint of posted range if higher.
3. Different currency? → target midpoint of their range. Convert if needed.
4. No salary info anywhere → use ${salary_expect} {currency}.
5. Asked for a range → posted midpoint ±10%. No posted range →
   "${salary_low}-${salary_high} {currency}".
6. Hourly → divide your annual answer by 2080.

== SCREENING QUESTIONS (be strategic) ==
Hard facts → answer truthfully from profile (location, citizenship, clearance,
licenses, criminal/background).
Skills/tools → be confident. This candidate is a {target_title} with
{years} years experience. "Do you have experience with [tool]?" in the same
domain (DevOps, backend, ML, cloud, automation) → YES. Engineers learn tools fast.
Open-ended ("Why do you want this role?", "Tell us about yourself") → 2-3
sentences. Specific to THIS job. Reference something from the job description.
No generic fluff. Sound like a real person.
EEO/demographics → "Decline to self-identify" or "Prefer not to say".

== STEP-BY-STEP ==
1. navigate(url). screenshot("landing"). solve_captcha() if detect returns one.
2. Read page. LOCATION CHECK. If ineligible, done(RESULT:FAILED:not_eligible_location).
3. Find Apply button. If "email resume to X":
     send_email(to=…, subject="Application for {title} — {display_name}",
                body=<2-3 sentence pitch + contact>, attachments=[resume_pdf])
     done(RESULT:APPLIED).
   After clicking Apply: snapshot. CAPTCHA DETECT — many sites trigger here.
4. Login wall?
   4a. URL is accounts.google.com / login.microsoftonline.com / okta.com /
       auth0.com / sso.cisco.com / any SSO → done(RESULT:FAILED:sso_required).
   4b. tabs("list") — new popup? Switch with tabs("select"). SSO there too?
       → sso_required.
   4c. Employer's own login form → sign in with {email} / {password}.
   4d. After Login click → CAPTCHA DETECT (login pages often have invisible CAPTCHAs).
   4e. Sign in fails → try sign up with same email/password.
   4f. Need email verification → search_emails + read_email to fetch code.
   4g. tabs("list") again. Switch back to application tab.
   4h. All failed → done(RESULT:FAILED:login_issue). Do not loop.
5. Upload resume. ALWAYS upload fresh — delete existing first, then upload
   bundle/resume.pdf.
6. Upload cover letter if there's a field. Text field → paste; file → upload PDF.
7. Check ALL pre-filled fields. ATS parsers auto-fill — often WRONG.
   - "Current Job Title" → use the title from the TAILORED RESUME summary.
   - Compare every other field to the APPLICANT PROFILE. Fix mismatches.
   - Fill empty fields.
8. Answer screening questions per the rules above.
9. BEFORE clicking Submit/Apply, snapshot. Review EVERY field. Verify name,
   email, phone, location, work auth, resume uploaded, cover letter if applicable.
   Fix anything wrong. Only then click Submit.
   (Dry-run mode: review and done(RESULT:APPLIED, "dry run") WITHOUT clicking.)
10. After Submit: snapshot. CAPTCHA DETECT. tabs("list"). Look for thank-you /
    confirmation. done(RESULT:APPLIED).

== BROWSER EFFICIENCY ==
- snapshot ONCE per page. Then screenshot to verify (10× cheaper than re-snapshot).
- Re-snapshot only when you need element refs to click/fill.
- Multi-page forms (Workday, Taleo, iCIMS): snapshot each page, fill all,
  click Next, repeat.
- Fill ALL fields in ONE fill_form call.
- CAPTCHA AWARENESS: after navigate / Apply / Submit / Login / when stuck,
  run solve_captcha(). Invisible CAPTCHAs (Turnstile, reCAPTCHA v3) show no
  visual widget but block submissions silently.

== FORM TRICKS ==
- Popup/new tab → tabs("list") then tabs("select", idx).
- Upload-first pages (Workday/Lever/Ashby): click Select File, then upload,
  wait for parsing, then Next.
- Dropdown won't fill → click to open, click option.
- Checkbox won't check via fill → click it. Snapshot to verify.
- Phone with country prefix → type digits only: {phone_digits}.
- Date → {today_us}.
- Honeypot (hidden, "leave blank") → skip.
- Format-sensitive → read the placeholder, match exactly.

== ASK USER ONLY IF NECESSARY ==
If a form asks for something not in this prompt AND not in the profile
addendum, AND it's not a screening you can answer from profile facts:
  done(RESULT:FAILED:question_required, reason="<the question>")
NexScout's orchestrator will park the job, surface the question to the user
via OpenClaw, then retry on the next tick after the user answers. Don't make
something up.

== WHEN TO GIVE UP ==
- Same page 3 times no progress → done(RESULT:FAILED:stuck).
- "no longer accepting" / closed → done(RESULT:EXPIRED).
- 500 / blank → done(RESULT:FAILED:page_error).
Stop immediately. Output your RESULT. Do not loop."""


# Cover letter placeholder text (verbatim §13.4 fallback).
COVER_LETTER_PLACEHOLDER = (
    'None available. Skip if optional. If required,\n'
    'write 2 factual sentences: (1) relevant experience from resume matching\n'
    'this role, (2) available immediately and based in {city}.'
)


def _digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def _today_us(today_iso: str | None) -> str:
    """Return ``today`` formatted as ``MM/DD/YYYY``.

    If ``today_iso`` is supplied (test determinism), format from it; otherwise
    return the literal placeholder ``"{today MM/DD/YYYY}"`` so byte-equality
    tests can pin a fixed input.
    """
    if today_iso:
        from datetime import date

        try:
            d = date.fromisoformat(today_iso)
        except ValueError:
            return today_iso
        return d.strftime("%m/%d/%Y")
    return "{today MM/DD/YYYY}"


def _last_name(legal: str) -> str:
    parts = (legal or "").strip().split()
    return parts[-1] if parts else legal


def _auth_rule(profile: Profile) -> str:
    """Build the ``auth_rule`` line from profile.auth (§13.4)."""
    permit = (profile.auth.permit or "USC").strip()
    sponsor = "Yes" if profile.auth.sponsor else "No"
    return f"{permit}. Sponsorship needed: {sponsor}."


def _accept_cities(profile: Profile) -> str:
    cities: list[str] = []
    for loc in profile.search.locations:
        label = (loc.label or loc.q or "").strip()
        if label and label.lower() not in {"remote", "remote us", "anywhere"}:
            cities.append(label)
    if profile.me.city and profile.me.city not in cities:
        cities.insert(0, profile.me.city)
    return ", ".join(cities) if cities else profile.me.city or "your city"


def _target_title(profile: Profile) -> str:
    if profile.exp.target_titles:
        return profile.exp.target_titles[0]
    return profile.exp.current_title or "senior engineer"


def _display_name(profile: Profile) -> str:
    return profile.me.pref or profile.me.legal


def _resolved_bundle_dir(bundle_dir: str | None) -> str:
    return bundle_dir or "."


def build_prompt(
    *,
    job: dict[str, Any],
    tailored_resume: str,
    cover_letter: str | None,
    dry_run: bool,
    profile: Profile,
    bundle_dir: str | None = None,
    today_iso: str | None = None,
) -> str:
    """Return the §13.4 system prompt with all substitutions filled in.

    Parameters
    ----------
    job
        Dict-like row from the ``jobs`` table; uses ``url``, ``application_url``,
        ``title``, ``site``, ``fit_score``.
    tailored_resume
        Plain-text resume produced by the tailor stage.
    cover_letter
        Plain-text cover letter, or ``None`` if not generated.
    dry_run
        Currently unused in the template itself but available to callers.
    profile
        Full :class:`Profile` — every "applicant profile" line draws from here.
    bundle_dir
        Absolute path to ``~/.nexscout/applications/<job_id>``; if ``None`` the
        prompt prints bare filenames.
    today_iso
        ISO-8601 date string for ``{today MM/DD/YYYY}`` substitution. ``None``
        keeps the literal placeholder so byte-equality tests can pin a fixed
        input.
    """
    job_url = str(job.get("application_url") or job.get("url") or "")
    cover_text = (cover_letter or "").strip() or COVER_LETTER_PLACEHOLDER.format(city=profile.me.city)

    me = profile.me
    pay = profile.pay
    auth = profile.auth
    eeo = profile.eeo
    exp = profile.exp

    # Pay range — fall back to (expect-15K, expect+15K) when no range is set.
    if pay.range and len(pay.range) >= 2 and pay.range[0] and pay.range[1]:
        salary_low = pay.range[0]
        salary_high = pay.range[1]
    else:
        salary_low = max(0, (pay.expect or 0) - 15000)
        salary_high = (pay.expect or 0) + 15000

    # Note: dry_run is reflected in the agent's done() rather than the prompt
    # template itself (step 9 says "Dry-run mode: …"). Surface a hint in logs.
    _ = dry_run

    return SYSTEM_PROMPT_TEMPLATE.format(
        job_url=job_url,
        title=str(job.get("title") or ""),
        site=str(job.get("site") or ""),
        fit_score=int(job.get("fit_score") or 0),
        bundle_dir=_resolved_bundle_dir(bundle_dir),
        tailored_resume_text=(tailored_resume or "").strip(),
        cover_letter_text=cover_text,
        legal_name=me.legal,
        pref_name=me.pref or me.legal,
        last_name=_last_name(me.legal),
        email=me.email,
        password=profile.password or "(prompt user)",
        phone=me.phone,
        phone_digits=_digits_only(me.phone),
        address=me.address,
        city=me.city,
        region=me.region,
        country=me.country,
        postcode=me.postcode,
        linkedin=me.links.li,
        github=me.links.gh,
        portfolio=me.links.portfolio,
        website=me.links.web,
        work_auth="Yes" if auth.authorized else "No",
        sponsor="Yes" if auth.sponsor else "No",
        permit=auth.permit,
        salary_expect=pay.expect,
        salary_low=salary_low,
        salary_high=salary_high,
        currency=pay.currency,
        years=exp.years,
        education=exp.edu,
        available=profile.avail.start,
        eeo_gender=eeo.gender,
        eeo_race=eeo.race,
        eeo_veteran=eeo.veteran,
        eeo_disability=eeo.disability,
        auth_rule=_auth_rule(profile),
        accept_cities=_accept_cities(profile),
        target_title=_target_title(profile),
        display_name=_display_name(profile),
        today_us=_today_us(today_iso),
    )


__all__ = [
    "COVER_LETTER_PLACEHOLDER",
    "SYSTEM_PROMPT_TEMPLATE",
    "build_prompt",
]
