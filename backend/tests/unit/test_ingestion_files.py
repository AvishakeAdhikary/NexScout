import uuid
from pathlib import Path

import pytest

from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.ingestion.files import FileKind, safe_filename, sniff
from nexscout.infrastructure.ingestion.parsers import parse_bytes, parse_isolated
from nexscout.infrastructure.storage import LocalObjectStore
from tests.fixtures.documents import ada_cv_text, make_docx, make_pdf

MB = 1024 * 1024


def test_sniff_by_content_not_name() -> None:
    pdf = make_pdf([["Hello"]])
    assert sniff(pdf, "cv.txt", MB).kind is FileKind.PDF
    assert sniff(make_docx(["Hi"]), "cv.pdf", MB).kind is FileKind.DOCX
    assert sniff(b"# Title\n", "notes.md", MB).kind is FileKind.MARKDOWN
    assert sniff(b"plain", "notes.bin", MB).kind is FileKind.TEXT


@pytest.mark.parametrize(
    ("data", "msg"),
    [
        (b"", "empty"),
        (b"MZ\x90\x00\x03\x00\x00\x00", "Unsupported"),  # Windows executable
        (b"PK\x03\x04not-a-docx", "Unsupported"),  # zip that isn't a Word document
        (b"\xff\xfe\x00\x00binary", "Unsupported"),
    ],
)
def test_sniff_rejects(data: bytes, msg: str) -> None:
    with pytest.raises(ValidationFailed, match=msg):
        sniff(data, "x", MB)


def test_size_limit() -> None:
    with pytest.raises(ValidationFailed, match="too large"):
        sniff(b"a" * (MB + 1), "big.txt", MB)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\cv.pdf", "cv.pdf"),
        ("", "document"),
        ("evil\x00name.pdf", "evilname.pdf"),
        ("....", "document"),
    ],
)
def test_safe_filename(name: str, expected: str) -> None:
    assert safe_filename(name) == expected


def test_parse_pdf_pages_and_offsets() -> None:
    parsed = parse_bytes(
        make_pdf([["Education", "MSc, Example University"], ["Skills", "Python"]]), FileKind.PDF
    )
    assert parsed.page_count == 2
    assert "Example University" in parsed.text
    assert parsed.page_of(parsed.text.index("Python")) == 2
    assert parsed.page_of(parsed.text.index("Education")) == 1


def test_parse_docx_and_markdown() -> None:
    docx_text = parse_bytes(make_docx(ada_cv_text().splitlines()), FileKind.DOCX).text
    assert "Examplecorp GmbH" in docx_text
    md = parse_bytes(ada_cv_text().encode(), FileKind.MARKDOWN)
    assert md.page_count is None
    assert md.page_of(5) is None


def test_corrupt_pdf_is_a_clean_validation_error() -> None:
    with pytest.raises(ValidationFailed):
        parse_bytes(b"%PDF-1.4\n garbage garbage", FileKind.PDF)


def test_isolated_parse_matches_in_process() -> None:
    data = make_pdf([["Skills", "Python, SQL"]])
    assert parse_isolated(data, FileKind.PDF).text == parse_bytes(data, FileKind.PDF).text


def test_isolated_parse_reports_validation_errors() -> None:
    with pytest.raises(ValidationFailed):
        parse_isolated(b"%PDF-1.4\n garbage", FileKind.PDF)


def test_object_store_roundtrip_and_key_safety(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    owner = uuid.uuid4()
    key, digest = store.put(owner, b"hello")
    assert key == f"{owner}/{digest[:2]}/{digest}"
    assert store.get(key) == b"hello"
    assert store.put(owner, b"hello") == (key, digest)  # idempotent
    store.delete(key)
    assert not store.exists(key)
    for bad in ("../x", f"{owner}/../../etc/passwd", "a/b/c"):
        with pytest.raises(ValueError, match="Invalid storage key"):
            store.get(bad)
