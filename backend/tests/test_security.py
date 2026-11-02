import jwt
import pytest

from app.crypto import decrypt, encrypt
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_encrypt_decrypt_roundtrip():
    secret = "public-community-string"
    token = encrypt(secret)
    assert token != secret
    assert decrypt(token) == secret


def test_encrypt_none_and_empty():
    assert encrypt(None) is None
    assert encrypt("") is None
    assert decrypt(None) is None


def test_ciphertext_is_nondeterministic():
    # Random nonce -> different ciphertext each call.
    assert encrypt("same") != encrypt("same")


def test_password_hash_and_verify():
    h = hash_password("correct horse")
    assert h != "correct horse"
    assert verify_password("correct horse", h) is True
    assert verify_password("wrong", h) is False


def test_verify_bad_hash_is_false():
    assert verify_password("x", "not-a-valid-hash") is False


def test_access_token_roundtrip():
    tok = create_access_token(42, "admin")
    claims = decode_token(tok, expected_type="access")
    assert claims["sub"] == "42"
    assert claims["role"] == "admin"


def test_token_type_enforced():
    refresh = create_refresh_token(1)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, expected_type="access")
