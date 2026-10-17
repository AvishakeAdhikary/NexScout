"""Upload hardening: hostile and malformed files are rejected cleanly, never crash the API,
never escape storage, and never execute anything."""

import contextlib
import io
import os
import random
import zipfile
from typing import Any

import httpx
import pytest

from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.ingestion.files import safe_filename, sniff
from tests.helpers import create_case, register, upload

pytestmark = pytest.mark.db
MB = 1024 * 1024


def _docx(members: dict[str, bytes], level: int = 9) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_docx_zip_bomb_is_rejected_before_inflating() -> None:
    bomb = _docx({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"\0" * (120 * MB)})
    assert len(bomb) < 1 * MB  # tiny on the wire
    with pytest.raises(ValidationFailed, match="unsafe size"):
        sniff(bomb, "cv.docx", 15 * MB)
    ratio = _docx({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"a" * (5 * MB)})
    with pytest.raises(ValidationFailed, match="unsafe size"):
        sniff(ratio, "cv.docx", 15 * MB)
    many = _docx(
        {
            "[Content_Types].xml": b"x",
            "word/document.xml": b"x",
            **{f"f{i}": b"x" for i in range(2_100)},
        }
    )
    with pytest.raises(ValidationFailed, match="unsafe size"):
        sniff(many, "cv.docx", 15 * MB)


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\x.md",
        "/abs/path.md",
        "C:\\x\\y.md",
        "a\x00b.md",
        "con.md",
        "\u202egnp.md",
        "x" * 5000 + ".md",
        "",
        None,
        "....",
        " . ",
    ],
)
def test_filenames_are_display_only_and_bounded(name: str | None) -> None:
    safe = safe_filename(name)
    assert "/" not in safe
    assert "\\" not in safe
    assert "\x00" not in safe
    assert 0 < len(safe) <= 200
    assert "\u202e" not in safe  # no bidi tricks


def test_random_bytes_never_crash_sniffing() -> None:
    rng = random.Random(1234)
    for _ in range(300):
        data = bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 4096)))
        for prefix in (b"", b"%PDF-", b"PK\x03\x04"):
            # A clean rejection is the expected outcome for garbage; anything else fails.
            with contextlib.suppress(ValidationFailed):
                sniff(prefix + data, "x.pdf", 15 * MB)


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"MZ\x90\x00" + os.urandom(64), "cv.pdf"),  # Windows executable renamed
        (b"\x7fELF" + os.urandom(64), "cv.md"),  # Linux executable
        (b"\x89PNG\r\n\x1a\n" + os.urandom(64), "cv.md"),  # image
        (_docx({"a.txt": b"hello"}), "cv.docx"),  # a zip that isn't a Word file
        (b"<script>alert(1)</script>\x00", "cv.html"),  # binary-ish html
    ],
)
async def test_hostile_uploads_get_clean_422(
    client: httpx.AsyncClient, data: bytes, name: str
) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    resp = await upload(client, case_id, data, name)
    assert resp.status_code == 422, resp.text
    body: dict[str, Any] = resp.json()
    assert "Traceback" not in resp.text
    assert body["code"] == "validation_failed"


async def test_corrupt_pdf_is_stored_but_reported_unreadable(client: httpx.AsyncClient) -> None:
    await register(client)
    case_id = str((await create_case(client))["id"])
    resp = await upload(client, case_id, b"%PDF-1.7\n" + os.urandom(2000), "scan.pdf")
    assert resp.status_code == 201  # stored; reading fails safely in the background
    doc_id = resp.json()["document"]["id"]
    download = await client.get(f"/api/v1/documents/{doc_id}/content")
    assert download.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in download.headers["content-security-policy"]
