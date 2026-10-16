import pytest

from nexscout.domain.errors import ValidationFailed
from nexscout.infrastructure.db.base import new_id
from nexscout.infrastructure.security.passwords import (
    hash_password,
    validate_password_policy,
    verify_password,
)
from nexscout.infrastructure.security.tokens import new_token, token_digest, tokens_equal


def test_password_roundtrip_uses_argon2id() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong password entirely")


def test_unknown_account_never_verifies() -> None:
    assert verify_password(None, "nexscout-timing-equalizer-not-a-real-password") is False


@pytest.mark.parametrize("bad", ["short", " leading-space-password", "x" * 300])
def test_password_policy(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        validate_password_policy(bad)


def test_tokens_are_random_and_digests_stable() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 43
    assert token_digest(a) == token_digest(a)
    assert len(token_digest(a)) == 64
    assert tokens_equal(a, a)
    assert not tokens_equal(a, b)


def test_uuid7_version_variant_and_ordering() -> None:
    ids = [new_id() for _ in range(50)]
    assert all(i.version == 7 and i.variant == "specified in RFC 4122" for i in ids)
    # Timestamp prefix is monotonic non-decreasing across calls.
    prefixes = [i.int >> 80 for i in ids]
    assert prefixes == sorted(prefixes)
    assert len(set(ids)) == len(ids)
