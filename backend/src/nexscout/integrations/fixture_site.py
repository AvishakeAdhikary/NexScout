# ruff: noqa: E501  (inline demo HTML)
"""A demo employer application site for development and tests (never mounted in production).

Clearly labelled on every page. Variants exercise the browser workflow's safety paths:
- `/apply/<anything>`: a normal form (name, email, phone, a motivation question, CV and cover
  letter uploads, a declaration checkbox) → confirmation page with a reference number.
- `/apply/captcha-*`: a CAPTCHA wall (NexScout must stop and hand over to the user).
- `/apply/login-*`: a login wall (NexScout never logs in for the user).
- `/apply/uncertain-*`: the form submits but the response doesn't confirm anything.
Submissions are kept in memory (`GET /_submissions`) so tests can assert exactly-once.
"""

from __future__ import annotations

import html
import itertools
import threading
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.datastructures import UploadFile

BANNER = (
    "<p style='background:#ffe066;padding:6px'><strong>NexScout demo application site.</strong> "
    "Not a real employer. Nothing submitted here goes anywhere.</p>"
)
_lock = threading.Lock()
_counter = itertools.count(1001)
SUBMISSIONS: list[dict[str, Any]] = []


def _page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"</head><body>{BANNER}<h1>{html.escape(title)}</h1>{body}</body></html>"
    )


FORM = """
<form method="post" enctype="multipart/form-data">
  <p><label for="full_name">Full name *</label><br><input id="full_name" name="full_name" required></p>
  <p><label for="email">Email address *</label><br><input id="email" name="email" type="email" required></p>
  <p><label for="phone">Phone</label><br><input id="phone" name="phone" type="tel"></p>
  <p><label for="motivation">Why are you interested in this role? *</label><br>
     <textarea id="motivation" name="motivation" rows="5" cols="60" required></textarea></p>
  <p><label for="cv">CV / résumé (PDF) *</label><br><input id="cv" name="cv" type="file" accept=".pdf" required></p>
  <p><label for="cover_letter">Cover letter (PDF)</label><br><input id="cover_letter" name="cover_letter" type="file" accept=".pdf"></p>
  <p><input id="newsletter" name="newsletter" type="checkbox"> <label for="newsletter">Send me job alerts</label></p>
  <p><input id="declaration" name="declaration" type="checkbox" required>
     <label for="declaration">I confirm that the information in this application is accurate and complete.</label></p>
  <p><button type="submit">Submit application</button></p>
</form>"""


def create_fixture_site() -> FastAPI:
    site = FastAPI(
        title="NexScout demo application site", docs_url=None, redoc_url=None, openapi_url=None
    )

    @site.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return _page("Demo careers", "<p>Use <code>/apply/&lt;job&gt;</code> to apply.</p>")

    @site.get("/apply/{job}", response_class=HTMLResponse)
    async def form(job: str) -> HTMLResponse:
        if job.startswith("captcha"):
            return _page(
                "Security check",
                "<p>Please verify you are human before applying.</p>"
                "<div class='g-recaptcha'>[ I'm not a robot ]</div>",
            )
        if job.startswith("login"):
            return _page(
                "Sign in to apply",
                "<form><label for='u'>Email</label><input id='u'>"
                "<label for='p'>Password</label><input id='p' type='password'>"
                "<button>Sign in</button></form>",
            )
        return _page(f"Apply: {job}", FORM)

    @site.post("/apply/{job}", response_class=HTMLResponse)
    async def submit(job: str, request: Request) -> HTMLResponse:
        data = await request.form()
        missing = [
            k for k in ("full_name", "email", "motivation", "declaration") if not data.get(k)
        ]
        cv = data.get("cv")
        if not isinstance(cv, UploadFile) or not cv.filename:
            missing.append("cv")
        if missing:
            return _page(
                "Please fix the errors", f"<p>Missing: {html.escape(', '.join(missing))}</p>"
            )
        files = {}
        for key in ("cv", "cover_letter"):
            f = data.get(key)
            if isinstance(f, UploadFile) and f.filename:
                content = await f.read()
                files[key] = {
                    "filename": f.filename,
                    "size": len(content),
                    "is_pdf": content.startswith(b"%PDF"),
                }
        with _lock:
            ref = f"FX-{next(_counter)}"
            SUBMISSIONS.append(
                {
                    "job": job,
                    "reference": ref,
                    "full_name": data.get("full_name"),
                    "email": data.get("email"),
                    "phone": data.get("phone") or None,
                    "motivation": data.get("motivation"),
                    "newsletter": bool(data.get("newsletter")),
                    "declaration": bool(data.get("declaration")),
                    "files": files,
                }
            )
        if job.startswith("uncertain"):
            return _page("Processing", "<p>We are processing your request. Please wait.</p>")
        return _page(
            "Application received",
            f"<p>Thank you for applying. Your application has been received.</p>"
            f"<p>Reference: <strong>{ref}</strong></p>",
        )

    @site.get("/_submissions")
    async def submissions() -> JSONResponse:
        with _lock:
            return JSONResponse(list(SUBMISSIONS))

    return site
