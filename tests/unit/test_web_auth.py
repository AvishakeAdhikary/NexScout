"""Signed cookie roundtrip + password helpers."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from nexscout.web import auth as web_auth


def test_signing_key_persists_across_calls(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.toml"
    k1 = web_auth.get_or_create_signing_key(secrets_path)
    k2 = web_auth.get_or_create_signing_key(secrets_path)
    assert k1 == k2
    assert len(k1) >= 32


def test_session_roundtrip(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.toml"
    web_toml_path = tmp_path / "web.toml"
    auth = web_auth.build_auth(secrets_path=secrets_path, web_toml_path=web_toml_path)
    payload = web_auth.make_session_payload("alice")
    cookie = web_auth.sign_session(auth, payload)
    out = web_auth.load_session(auth, cookie)
    assert out is not None
    assert out["user"] == "alice"


def test_session_tampered_cookie_rejected(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.toml"
    auth = web_auth.build_auth(secrets_path=secrets_path, web_toml_path=tmp_path / "web.toml")
    payload = web_auth.make_session_payload("alice")
    cookie = web_auth.sign_session(auth, payload)
    tampered = cookie[:-2] + ("AA" if cookie[-2:] != "AA" else "BB")
    assert web_auth.load_session(auth, tampered) is None


def test_session_expired(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.toml"
    auth = web_auth.build_auth(secrets_path=secrets_path, web_toml_path=tmp_path / "web.toml")
    payload = web_auth.make_session_payload("alice")
    cookie = web_auth.sign_session(auth, payload)
    # itsdangerous TimestampSigner uses integer-seconds timestamps; sleep > 2s
    # to safely cross a tick boundary on any starting epoch.
    time.sleep(2.1)
    assert web_auth.load_session(auth, cookie, max_age=1) is None


def test_session_load_handles_none() -> None:
    secrets_path = Path("/tmp/secrets-nx.toml")
    auth = web_auth.build_auth(secrets_path=secrets_path, web_toml_path=Path("/tmp/web-nx.toml"))
    assert web_auth.load_session(auth, None) is None
    assert web_auth.load_session(auth, "") is None


class TestPassword:
    def test_hash_and_verify(self) -> None:
        bcrypt_avail = True
        try:
            import bcrypt  # noqa: F401
        except ImportError:
            bcrypt_avail = False
        if not bcrypt_avail:
            pytest.skip("bcrypt not installed")
        h = web_auth.hash_password("hunter2")
        assert web_auth.verify_password("hunter2", h)
        assert not web_auth.verify_password("wrong", h)

    def test_set_and_get_password(self, tmp_path: Path) -> None:
        try:
            import bcrypt  # noqa: F401
        except ImportError:
            pytest.skip("bcrypt not installed")
        p = tmp_path / "web.toml"
        assert web_auth.get_password_hash(p) is None
        web_auth.set_password("hunter2", p)
        stored = web_auth.get_password_hash(p)
        assert stored is not None
        assert web_auth.verify_password("hunter2", stored)


class TestCsrf:
    def test_token_is_nontrivial(self) -> None:
        t = web_auth.issue_csrf_token()
        assert len(t) >= 16

    def test_double_submit_check(self) -> None:
        t = web_auth.issue_csrf_token()
        assert web_auth.csrf_ok(header=t, cookie=t)
        assert not web_auth.csrf_ok(header=t, cookie=t + "x")
        assert not web_auth.csrf_ok(header=None, cookie=t)
        assert not web_auth.csrf_ok(header=t, cookie=None)
