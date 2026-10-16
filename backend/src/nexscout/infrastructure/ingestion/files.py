"""Upload validation: size limits and content sniffing (never trust filename or client MIME)."""

from __future__ import annotations

import io
import unicodedata
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

import filetype

from nexscout.domain.errors import ValidationFailed

MAX_FILENAME = 200


class FileKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "markdown"
    TEXT = "text"


CONTENT_TYPES: dict[FileKind, str] = {
    FileKind.PDF: "application/pdf",
    FileKind.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    FileKind.MARKDOWN: "text/markdown; charset=utf-8",
    FileKind.TEXT: "text/plain; charset=utf-8",
}


@dataclass(frozen=True)
class SniffedFile:
    kind: FileKind
    content_type: str
    filename: str


def safe_filename(name: str | None) -> str:
    """Display-only filename: basename, no control chars, bounded length."""
    base = PurePath((name or "").replace("\\", "/")).name
    cleaned = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C").strip(" .")
    return (cleaned or "document")[:MAX_FILENAME]


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            return "[Content_Types].xml" in names and "word/document.xml" in names
    except zipfile.BadZipFile:
        return False


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def sniff(data: bytes, filename: str | None, max_bytes: int) -> SniffedFile:
    """Identify the file by its bytes. Only PDF, DOCX, Markdown and plain text are accepted."""
    if not data:
        raise ValidationFailed("The file is empty.")
    if len(data) > max_bytes:
        raise ValidationFailed(f"The file is too large (limit {max_bytes // (1024 * 1024)} MB).")
    name = safe_filename(filename)
    suffix = PurePath(name).suffix.lower()
    if data.startswith(b"%PDF-"):
        kind = FileKind.PDF
    elif data.startswith(b"PK\x03\x04") and _is_docx(data):
        kind = FileKind.DOCX
    elif data.startswith(b"PK\x03\x04") or filetype.guess(data) is not None:
        # Any other recognized binary format (archives, executables, images...) is rejected,
        # even if its bytes happen to decode as UTF-8.
        raise ValidationFailed(
            "Unsupported file type. Upload a PDF, Word (.docx), Markdown, or plain-text file."
        )
    elif _is_text(data):
        kind = FileKind.MARKDOWN if suffix in {".md", ".markdown"} else FileKind.TEXT
    else:
        raise ValidationFailed(
            "Unsupported file type. Upload a PDF, Word (.docx), Markdown, or plain-text file."
        )
    return SniffedFile(kind=kind, content_type=CONTENT_TYPES[kind], filename=name)
