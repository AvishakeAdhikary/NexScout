"""Envelope encryption for stored secrets (AES-256-GCM).

The master key comes from `NEXSCOUT_MASTER_KEY` (base64, 32 bytes). In development, if none is
set, a random key file is created next to the storage directory. Production refuses to run
without an explicit key. Ciphertexts are bound to their owner and purpose with associated data,
so a row copied to another user or purpose fails to decrypt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from nexscout.config import Settings
from nexscout.domain.errors import DomainError


class SecretsUnavailable(DomainError):
    code = "secrets_unavailable"


@dataclass(frozen=True)
class SealedSecret:
    ciphertext: bytes
    nonce: bytes
    key_id: str


class SecretBox:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise SecretsUnavailable("The master key must be 32 bytes.")
        self._aead = AESGCM(key)
        self._derive_key = hashlib.sha256(b"nexscout-derive:" + key).digest()
        self.key_id = hashlib.sha256(key).hexdigest()[:12]

    def derive(self, label: str) -> str:
        """A stable, non-reversible token for `label` (e.g. a webhook verify token)."""
        return hmac.new(self._derive_key, label.encode(), hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def _aad(owner_id: uuid.UUID, purpose: str) -> bytes:
        return f"{owner_id}:{purpose}".encode()

    def seal(self, plaintext: str, *, owner_id: uuid.UUID, purpose: str) -> SealedSecret:
        nonce = os.urandom(12)
        ct = self._aead.encrypt(nonce, plaintext.encode(), self._aad(owner_id, purpose))
        return SealedSecret(ct, nonce, self.key_id)

    def open(self, sealed: SealedSecret, *, owner_id: uuid.UUID, purpose: str) -> str:
        if sealed.key_id != self.key_id:
            raise SecretsUnavailable("This secret was encrypted with a different master key.")
        return self._aead.decrypt(
            sealed.nonce, sealed.ciphertext, self._aad(owner_id, purpose)
        ).decode()


def load_secret_box(settings: Settings) -> SecretBox:
    if settings.master_key is not None and settings.master_key.get_secret_value():
        try:
            key = base64.b64decode(settings.master_key.get_secret_value(), validate=True)
        except ValueError as exc:
            raise SecretsUnavailable("NEXSCOUT_MASTER_KEY is not valid base64.") from exc
        return SecretBox(key)
    if settings.is_production:
        raise SecretsUnavailable("NEXSCOUT_MASTER_KEY must be set in production.")
    key_file = Path(settings.storage_dir).resolve().parent / "master.key"
    if not key_file.exists():
        key_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64encode(os.urandom(32)))
    return SecretBox(base64.b64decode(key_file.read_bytes()))


def hint(secret: str) -> str:
    """Last 4 characters only, for display ("…abcd")."""
    return f"…{secret[-4:]}" if len(secret) >= 8 else "…"
