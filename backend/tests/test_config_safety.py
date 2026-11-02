"""Production safety guard: the app must refuse to boot in production while any
insecure development-default secret is still in use."""
import pytest

from app.config import (
    DEV_ADMIN_PASSWORD,
    DEV_JWT_SECRET,
    DEV_MASTER_KEY,
    Settings,
    production_safety_check,
)

_STRONG = dict(
    jwt_secret="s3cure-" + "x" * 40,
    master_key="m4ster-" + "y" * 40,
    admin_password="a-strong-admin-password-123",
)
_DEFAULTS = dict(
    jwt_secret=DEV_JWT_SECRET,
    master_key=DEV_MASTER_KEY,
    admin_password=DEV_ADMIN_PASSWORD,
)


def test_insecure_defaults_detected():
    s = Settings(**_DEFAULTS)
    assert set(s.insecure_defaults_in_use()) == {"jwt_secret", "master_key", "admin_password"}


def test_no_insecure_when_overridden():
    s = Settings(**_STRONG)
    assert s.insecure_defaults_in_use() == []


def test_production_refuses_insecure_defaults():
    s = Settings(environment="production", **_DEFAULTS)
    with pytest.raises(RuntimeError):
        production_safety_check(s)


def test_production_starts_with_strong_secrets():
    s = Settings(environment="production", **_STRONG)
    production_safety_check(s)  # must not raise


def test_dev_allows_defaults():
    s = Settings(environment="development", **_DEFAULTS)
    production_safety_check(s)  # dev is allowed to run with defaults
