"""Password hashing with argon2id."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from nexscout.domain.errors import ValidationFailed

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256

_hasher = PasswordHasher()  # argon2id with library-maintained secure defaults

# Pre-computed so unknown-account logins cost the same as real ones (timing equalization).
_DUMMY_HASH = _hasher.hash("nexscout-timing-equalizer-not-a-real-password")


def validate_password_policy(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationFailed(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationFailed(f"Password must be at most {MAX_PASSWORD_LENGTH} characters.")
    if password.strip() != password or not password.strip():
        raise ValidationFailed("Password must not start or end with whitespace.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-effort verification. Pass None for unknown accounts."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
