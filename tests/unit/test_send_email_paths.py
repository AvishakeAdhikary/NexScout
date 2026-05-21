"""``send_email`` covers three transports: explicit factory, SMTP from profile,
Gmail browser-login fallback.

No real network calls are made.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from nexscout.apply.tools import send_email
from nexscout.core.profile import Profile

# ---------------------------------------------------------------------------
# Helpers — mock SMTP client + mock driver
# ---------------------------------------------------------------------------


class _MockSMTP:
    """Mock SMTP client matching the ``smtplib.SMTP`` surface we use."""

    instances: ClassVar[list[_MockSMTP]] = []

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.quit_called = False
        _MockSMTP.instances.append(self)

    def send_message(self, msg: Any) -> None:
        self.sent.append(msg)

    def quit(self) -> None:
        self.quit_called = True


class _GmailDriverOK:
    """Driver mock that emulates a successful Gmail compose+send flow."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.current_url = ""
        self.page_source = ""
        self.send_clicked = False
        self.attach_paths: list[str] = []

    def get(self, url: str) -> None:
        self.urls.append(url)
        self.current_url = url

    def find_elements(self, by: str, value: str) -> list[Any]:
        _ = by
        # Always pretend that login screens never appear (compose URL works).
        if "input[type=\"email\"]" in value or "Passwd" in value or "identifier" in value:
            return []
        # File input selector comes inside the dialog selector — check this
        # FIRST because the substring "dialog" also appears in it.
        if "input[type=\"file\"]" in value:
            return [_FileInput(self.attach_paths)]
        if "Send" in value or "aria-label^=\"Send\"" in value:
            return [_SendButton(self)]
        if "aria-live" in value:
            return [_Element()]
        if 'role="dialog"' in value or "dialog" in value:
            return [_Element()]
        return []

    def find_element(self, by: str, value: str) -> Any:
        els = self.find_elements(by, value)
        if not els:
            raise RuntimeError(f"no element for {value}")
        return els[0]


class _Element:
    def is_displayed(self) -> bool:
        return True

    def click(self) -> None:
        pass

    def clear(self) -> None:
        pass

    def send_keys(self, value: Any) -> None:
        pass


class _SendButton(_Element):
    def __init__(self, driver: _GmailDriverOK) -> None:
        self.driver = driver

    def click(self) -> None:
        self.driver.send_clicked = True


class _FileInput(_Element):
    def __init__(self, sink: list[str]) -> None:
        self.sink = sink

    def send_keys(self, value: Any) -> None:
        self.sink.append(str(value))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_smtp() -> None:
    _MockSMTP.instances.clear()


@pytest.fixture
def resume_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "resume.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    return p


@pytest.fixture
def bundle_dir(tmp_path: Path) -> Path:
    d = tmp_path / "bundle"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Path 1 — explicit smtp_factory (legacy / test injection)
# ---------------------------------------------------------------------------


def test_send_email_uses_explicit_smtp_factory(bundle_dir: Path, resume_pdf: Path) -> None:
    out = send_email(
        driver=None,
        args={
            "to": "hr@example.com",
            "subject": "Application",
            "body": "Hello",
            "attachments": [str(resume_pdf)],
        },
        bundle_dir=bundle_dir,
        smtp_factory=_MockSMTP,
    )
    assert out.ok, out.error
    assert len(_MockSMTP.instances) == 1
    assert _MockSMTP.instances[0].quit_called
    assert out.data.get("via") == "smtp"


# ---------------------------------------------------------------------------
# Path 2 — SMTP credentials from profile
# ---------------------------------------------------------------------------


def test_send_email_uses_smtp_from_profile(
    bundle_dir: Path, resume_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[Any] = []

    class _CapturedSMTP:
        def __init__(self, host: str, port: int, timeout: int = 0) -> None:
            self.host = host
            self.port = port
            sent.append(("init_ssl", host, port))

        def send_message(self, msg: Any) -> None:
            sent.append(("send", msg))

        def login(self, user: str, password: str) -> None:
            sent.append(("login", user, password))

        def quit(self) -> None:
            sent.append(("quit",))

    monkeypatch.setattr("smtplib.SMTP_SSL", _CapturedSMTP)

    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "j@e.com", "phone": "1"},
            "smtp": {
                "host": "smtp.example.com",
                "port": 465,
                "user": "j@e.com",
                "password": "secret",
                "use_ssl": True,
                "use_tls": False,
            },
        }
    )
    out = send_email(
        driver=None,
        args={
            "to": "hr@example.com",
            "subject": "Application",
            "body": "Hi",
            "attachments": [str(resume_pdf)],
        },
        bundle_dir=bundle_dir,
        profile=profile,
    )
    assert out.ok, out.error
    assert any(item[0] == "send" for item in sent)
    assert any(item == ("login", "j@e.com", "secret") for item in sent)


# ---------------------------------------------------------------------------
# Path 3 — Gmail browser fallback
# ---------------------------------------------------------------------------


def test_send_email_gmail_browser_fallback(bundle_dir: Path, resume_pdf: Path) -> None:
    profile = Profile.model_validate(
        {
            "me": {
                "legal": "Jane Public",
                "pref": "Jane",
                "email": "jane.public@gmail.com",
                "phone": "1",
            },
            "gmail_password": "abcd-efgh-ijkl-mnop",
            "smtp": {"host": ""},
        }
    )
    driver = _GmailDriverOK()
    out = send_email(
        driver=driver,
        args={
            "to": "hr@example.com",
            "subject": "Application for Staff Engineer",
            "body": "Hi there",
            "attachments": [str(resume_pdf)],
        },
        bundle_dir=bundle_dir,
        profile=profile,
    )
    assert out.ok, out.error
    assert out.data.get("via") == "gmail_browser"
    assert driver.send_clicked
    assert any(str(resume_pdf.resolve()) in p for p in driver.attach_paths)
    # The compose URL should have been navigated to.
    assert any("mail.google.com/mail" in u for u in driver.urls)


def test_send_email_returns_error_when_no_transport(bundle_dir: Path) -> None:
    profile = Profile.model_validate(
        {
            "me": {"legal": "Jane", "pref": "Jane", "email": "jane@yahoo.com", "phone": "1"},
        }
    )
    out = send_email(
        driver=None,
        args={"to": "hr@x.com", "subject": "Hi", "body": ""},
        bundle_dir=bundle_dir,
        profile=profile,
    )
    assert not out.ok
    assert "no email transport" in (out.error or "")


def test_send_email_validates_attachments_exist(bundle_dir: Path) -> None:
    out = send_email(
        driver=None,
        args={
            "to": "hr@x.com",
            "subject": "Hi",
            "body": "",
            "attachments": ["/nonexistent/file.pdf"],
        },
        bundle_dir=bundle_dir,
        smtp_factory=_MockSMTP,
    )
    assert not out.ok
    assert "attachment missing" in (out.error or "")
