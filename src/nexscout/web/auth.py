"""Web auth — bcrypt password + HMAC-signed session cookie + CSRF.

Two state files:

* ``~/.nexscout/web.toml`` — stores the bcrypt password hash.
* ``~/.nexscout/secrets.toml`` — stores the HMAC signing key (generated on
  first use).

Cookies:

* ``nexscout_session`` — HMAC-signed (``itsdangerous``) JSON blob; 24h TTL.
* ``nexscout_csrf`` — random per-session token; POSTs must echo it back as
  the ``X-CSRF-Token`` header (or ``_csrf`` form field).
"""

from __future__ import annotations

import json
import secrets
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomli_w
except ImportError:  # pragma: no cover — fallback writer

    class _TomliWFallback:
        @staticmethod
        def dumps(data: dict[str, Any]) -> str:
            lines: list[str] = []
            for k, v in data.items():
                if isinstance(v, str):
                    lines.append(f'{k} = "{v}"')
                elif isinstance(v, bool):
                    lines.append(f"{k} = {str(v).lower()}")
                else:
                    lines.append(f"{k} = {v!r}")
            return "\n".join(lines) + "\n"

    tomli_w = _TomliWFallback()  # type: ignore[assignment]

from itsdangerous import BadSignature, TimestampSigner

from ..core.config import nexscout_dir
from ..core.errors import ConfigError

#: Cookie name + max age (24 hours per §17).
SESSION_COOKIE = "nexscout_session"
CSRF_COOKIE = "nexscout_csrf"
SESSION_MAX_AGE_S = 24 * 60 * 60


@dataclass
class WebAuth:
    """Bundled auth context: signer + hashed password."""

    signer: TimestampSigner
    password_hash: bytes
    secrets_path: Path
    web_toml_path: Path


# ---------------------------------------------------------------------------
# bcrypt — soft dependency
# ---------------------------------------------------------------------------


def _bcrypt():
    try:
        import bcrypt  # type: ignore[import-untyped]
    except ImportError as e:  # pragma: no cover
        raise ConfigError("bcrypt is not installed; run `pip install bcrypt`") from e
    return bcrypt


def hash_password(password: str) -> bytes:
    bcrypt = _bcrypt()
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, hashed: bytes) -> bool:
    bcrypt = _bcrypt()
    try:
        return bool(bcrypt.checkpw(password.encode("utf-8"), hashed))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _web_toml_path() -> Path:
    return nexscout_dir() / "web.toml"


def _secrets_toml_path() -> Path:
    return nexscout_dir() / "secrets.toml"


def _load_toml(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    return tomllib.loads(p.read_text(encoding="utf-8"))


def _write_toml(p: Path, data: dict[str, Any]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tomli_w.dumps(data), encoding="utf-8")


def get_or_create_signing_key(path: Path | None = None) -> str:
    """Read (or generate + persist) the HMAC signing key."""
    p = path or _secrets_toml_path()
    data = _load_toml(p)
    key = data.get("session_key")
    if not isinstance(key, str) or len(key) < 32:
        key = secrets.token_urlsafe(48)
        data["session_key"] = key
        _write_toml(p, data)
    return key


def get_password_hash(path: Path | None = None) -> bytes | None:
    """Return the stored bcrypt password hash, or None if unset."""
    p = path or _web_toml_path()
    data = _load_toml(p)
    h = data.get("password_hash")
    if isinstance(h, str) and h:
        return h.encode("utf-8")
    return None


def set_password(password: str, path: Path | None = None) -> None:
    """Write ``password`` (bcrypt-hashed) to ``web.toml``."""
    p = path or _web_toml_path()
    data = _load_toml(p)
    data["password_hash"] = hash_password(password).decode("utf-8")
    _write_toml(p, data)


def build_auth(*, secrets_path: Path | None = None, web_toml_path: Path | None = None) -> WebAuth:
    """Build a :class:`WebAuth` from the on-disk state."""
    secrets_path = secrets_path or _secrets_toml_path()
    web_toml_path = web_toml_path or _web_toml_path()
    key = get_or_create_signing_key(secrets_path)
    password_hash = get_password_hash(web_toml_path) or b""
    return WebAuth(
        signer=TimestampSigner(key),
        password_hash=password_hash,
        secrets_path=secrets_path,
        web_toml_path=web_toml_path,
    )


# ---------------------------------------------------------------------------
# Session cookies
# ---------------------------------------------------------------------------


def sign_session(auth: WebAuth, payload: dict[str, Any]) -> str:
    """Sign and return the cookie value."""
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return auth.signer.sign(raw).decode("utf-8")


def load_session(auth: WebAuth, cookie_value: str | None, *, max_age: int = SESSION_MAX_AGE_S) -> dict[str, Any] | None:
    """Verify + parse a session cookie. Returns ``None`` on failure/expiry."""
    if not cookie_value:
        return None
    try:
        raw = auth.signer.unsign(cookie_value, max_age=max_age)
    except BadSignature:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None


def make_session_payload(username: str = "owner") -> dict[str, Any]:
    return {"user": username, "iat": int(time.time())}


def issue_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_ok(*, header: str | None, cookie: str | None) -> bool:
    """Double-submit cookie check — header must match cookie, both non-empty."""
    if not header or not cookie:
        return False
    return secrets.compare_digest(header, cookie)


__all__ = [
    "CSRF_COOKIE",
    "SESSION_COOKIE",
    "SESSION_MAX_AGE_S",
    "WebAuth",
    "build_auth",
    "csrf_ok",
    "get_or_create_signing_key",
    "get_password_hash",
    "hash_password",
    "issue_csrf_token",
    "load_session",
    "make_session_payload",
    "set_password",
    "sign_session",
    "verify_password",
]
