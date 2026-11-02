from fastapi.testclient import TestClient

from app.config import get_settings


def test_login_success(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"email": "admin@rackmon.io", "password": "admin12345"})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"email": "admin@rackmon.io", "password": "nope"})
    assert r.status_code == 401


def test_login_unknown_user(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"email": "ghost@rackmon.io", "password": "x"})
    assert r.status_code == 401


def test_login_invalid_email_format(client: TestClient):
    r = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422


def test_me_requires_auth(client: TestClient):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_role(client: TestClient, admin_headers: dict):
    r = client.get("/api/v1/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_invalid_token_rejected(client: TestClient):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401


def test_refresh_flow(client: TestClient):
    login = client.post("/api/v1/auth/login", json={"email": "admin@rackmon.io", "password": "admin12345"})
    refresh_token = login.json()["refresh_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_refresh_rejects_access_token(client: TestClient):
    login = client.post("/api/v1/auth/login", json={"email": "admin@rackmon.io", "password": "admin12345"})
    access = login.json()["access_token"]
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert r.status_code == 401


def test_account_lockout_after_attempts(client: TestClient):
    settings = get_settings()
    for _ in range(settings.max_login_attempts):
        client.post("/api/v1/auth/login", json={"email": "viewer@rackmon.io", "password": "wrong"})
    # Even the correct password is now locked out.
    r = client.post(
        "/api/v1/auth/login",
        json={"email": settings.viewer_email, "password": settings.viewer_password},
    )
    assert r.status_code == 423


def test_logout(client: TestClient, admin_headers: dict):
    r = client.post("/api/v1/auth/logout", headers=admin_headers)
    assert r.status_code == 200
