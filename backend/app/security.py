"""Password hashing (Argon2id) and JWT tokens."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings

settings = get_settings()

API_KEY_PREFIX = "rkm_"


def hash_api_key(key: str) -> str:
    """API keys are high-entropy random tokens, so a fast unsalted SHA-256 is
    sufficient for lookup/verification (unlike user passwords)."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, sha256_hash). The full key is shown once."""
    full = f"{API_KEY_PREFIX}{secrets.token_hex(24)}"
    return full, full[:12], hash_api_key(full)

# Argon2id is the default variant in argon2-cffi.
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _ph.check_needs_rehash(password_hash)
    except Exception:
        return False


def _create_token(sub: str, token_type: str, ttl: timedelta, extra: dict | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, role: str, token_version: int = 0) -> str:
    return _create_token(
        str(user_id),
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        {"role": role, "tv": token_version},
    )


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.refresh_token_ttl_days),
        {"tv": token_version},
    )


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """Decode and validate a token. Raises jwt exceptions on failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if expected_type is not None and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload
