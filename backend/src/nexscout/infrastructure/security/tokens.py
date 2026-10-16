"""Opaque random tokens. Only SHA-256 digests are stored server-side."""

from __future__ import annotations

import hashlib
import hmac
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
