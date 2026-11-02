"""API keys: creation, X-API-Key authentication, and revocation (RF-48)."""
from __future__ import annotations


def _create_key(client, admin_headers, name="ci") -> dict:
    r = client.post("/api/v1/admin/apikeys", headers=admin_headers, json={"name": name})
    assert r.status_code == 201
    return r.json()


def test_create_returns_secret_once_and_list_hides_it(client, admin_headers):
    created = _create_key(client, admin_headers)
    assert created["key"].startswith("rkm_")
    assert created["prefix"] == created["key"][:12]

    listed = client.get("/api/v1/admin/apikeys", headers=admin_headers).json()
    row = next(k for k in listed if k["id"] == created["id"])
    assert "key" not in row  # secret never returned again
    assert row["revoked"] is False


def test_api_key_authenticates_requests(client, admin_headers):
    key = _create_key(client, admin_headers)["key"]
    # No bearer token — only the API key header.
    r = client.get("/api/v1/devices", headers={"X-API-Key": key})
    assert r.status_code == 200
    # Creator is an admin, so admin-only endpoints work too.
    assert client.get("/api/v1/admin/audit", headers={"X-API-Key": key}).status_code == 200


def test_revoked_key_is_rejected(client, admin_headers):
    created = _create_key(client, admin_headers)
    key = created["key"]
    assert client.get("/api/v1/overview", headers={"X-API-Key": key}).status_code == 200

    d = client.delete(f"/api/v1/admin/apikeys/{created['id']}", headers=admin_headers)
    assert d.status_code == 204
    assert client.get("/api/v1/overview", headers={"X-API-Key": key}).status_code == 401


def test_invalid_key_rejected(client):
    assert client.get("/api/v1/overview", headers={"X-API-Key": "rkm_deadbeef"}).status_code == 401


def test_only_admin_manages_keys(client, viewer_headers, operator_headers):
    assert client.get("/api/v1/admin/apikeys").status_code == 401
    assert client.get("/api/v1/admin/apikeys", headers=viewer_headers).status_code == 403
    assert client.post("/api/v1/admin/apikeys", headers=operator_headers,
                       json={"name": "x"}).status_code == 403
