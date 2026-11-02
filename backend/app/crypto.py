"""Symmetric encryption of secrets at rest (SNMP communities, SMTP passwords).

Uses AES-256-GCM with a key derived from the configured master key. The master
key lives outside the database (env/file/KMS) so a database leak does not expose
device credentials. Ciphertext is stored as base64 of ``nonce || ciphertext``.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings

_NONCE_LEN = 12  # 96-bit nonce recommended for GCM


def _key() -> bytes:
    # Derive a stable 32-byte key from whatever master_key string is provided.
    raw = get_settings().master_key.encode("utf-8")
    return hashlib.sha256(raw).digest()


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    aes = AESGCM(_key())
    nonce = os.urandom(_NONCE_LEN)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str | None) -> str | None:
    if token is None or token == "":
        return None
    raw = base64.b64decode(token)
    nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    aes = AESGCM(_key())
    return aes.decrypt(nonce, ct, None).decode("utf-8")
