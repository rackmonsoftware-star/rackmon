"""Shared test fixtures.

Environment is configured *before* the app is imported so the cached settings
pick up the test database and a disabled background poller. Each test runs
against a freshly created schema with the two seed users.
"""
from __future__ import annotations

import atexit
import os
import tempfile

# --- Configure the app for testing (must precede app import) --------------- #
#
# El nombre lleva el PID a propósito. Antes era un único "rackmon_test.db" en el
# temporal del sistema, así que DOS ejecuciones a la vez en la misma máquina
# —dos terminales, el runner del editor, o un proceso automático— compartían el
# mismo fichero. Como cada test hace drop_all + create_all, cada ejecución le
# borraba las tablas a la otra: salían decenas de "no such table: users" e
# IntegrityError que no tenían nada que ver con el código, y el fichero quedaba
# bloqueado. Con el PID, cada ejecución tiene la suya y no se pisan.
_TMP_DB = os.path.join(tempfile.gettempdir(), f"rackmon_test_{os.getpid()}.db")


@atexit.register
def _limpiar_base_de_pruebas() -> None:
    """No dejar un rastro de ficheros por el temporal del sistema."""
    for sufijo in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(_TMP_DB + sufijo)
        except OSError:
            pass
os.environ.update(
    RACKMON_ENVIRONMENT="test",
    RACKMON_DATABASE_URL=os.environ.get("RACKMON_TEST_DATABASE_URL", f"sqlite:///{_TMP_DB}"),
    RACKMON_POLLER_ENABLED="false",
    RACKMON_SEED_DEMO_DATA="false",
    RACKMON_JWT_SECRET="test-secret-key-for-pytest-000000000000000000",
    RACKMON_MASTER_KEY="test-master-key-for-pytest",
    RACKMON_MAX_LOGIN_ATTEMPTS="5",
    RACKMON_LOCKOUT_SECONDS="300",
    RACKMON_ADMIN_EMAIL="admin@rackmon.io",
    RACKMON_ADMIN_PASSWORD="admin12345",
    RACKMON_VIEWER_EMAIL="viewer@rackmon.io",
    # NO la de fábrica: esa está publicada en rackmon.app y desde ahora la cuenta
    # no se crea con ella fuera de la demo. Las pruebas usan la suya.
    RACKMON_VIEWER_PASSWORD="viewer-de-pruebas-8f21c",
)

import random  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
# Ya no se parchea nada de licencias: desde la 1.3.0 hay una sola edicion con
# todo encendido, asi que las pruebas no tienen que fabricarse una licencia Pro
# para ejercitar SSO, LDAP o los informes de SLA. Antes aqui se firmaba una con
# un par de claves efimero — y antes de eso, con la clave REAL del vendedor,
# escrita en este fichero y publicada sin querer en GitHub y en la imagen.
from app.services.alert_engine import engine as alert_engine  # noqa: E402
from app.services.poller import _last_polled, latest  # noqa: E402
from app.services.seed import seed_all  # noqa: E402

ADMIN = {"email": "admin@rackmon.io", "password": "admin12345"}
VIEWER = {"email": "viewer@rackmon.io", "password": "viewer-de-pruebas-8f21c"}


@pytest.fixture(autouse=True)
def _reset_state():
    """Fresh schema + seed users before every test; clear in-memory caches."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_all()
    alert_engine.reset()
    _last_polled.clear()
    latest._data.clear()
    # Deterministic simulator: the collector injects a rare (~0.2%) "unreachable"
    # sweep via random. A fixed seed keeps single-sweep tests from flaking on it
    # while preserving realistic variation in production (unseeded).
    from app.plugins import clear_channel_plugins
    clear_channel_plugins()
    random.seed(20240517)
    yield


@pytest.fixture()
def client() -> TestClient:
    # No context manager: we don't want the lifespan poller in tests.
    return TestClient(app)


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _token(client: TestClient, creds: dict) -> str:
    r = client.post("/api/v1/auth/login", json=creds)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture()
def admin_headers(client: TestClient) -> dict:
    return {"Authorization": f"Bearer {_token(client, ADMIN)}"}


@pytest.fixture()
def viewer_headers(client: TestClient) -> dict:
    return {"Authorization": f"Bearer {_token(client, VIEWER)}"}


@pytest.fixture()
def operator_headers(client: TestClient, admin_headers: dict) -> dict:
    """Create an operator via the admin API and return its auth headers."""
    email = "operator@rackmon.io"
    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"email": email, "password": "operator123", "role": "operator"},
    )
    return {"Authorization": f"Bearer {_token(client, {'email': email, 'password': 'operator123'})}"}


@pytest.fixture()
def sample_device(client: TestClient, operator_headers: dict) -> dict:
    r = client.post(
        "/api/v1/devices",
        headers=operator_headers,
        json={
            "name": "test-node-01", "ip": "10.0.0.5", "snmp_version": "2c",
            "snmp_community": "s3cret", "rack": "RACK-T", "position_u": 10,
            "vendor": "Dell", "tags": ["test", "compute"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
