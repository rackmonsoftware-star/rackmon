from fastapi.testclient import TestClient


def test_list_users_admin_only(client: TestClient, admin_headers: dict, viewer_headers: dict):
    assert client.get("/api/v1/admin/users", headers=admin_headers).status_code == 200
    assert client.get("/api/v1/admin/users", headers=viewer_headers).status_code == 403


def test_create_user_and_login(client: TestClient, admin_headers: dict):
    r = client.post("/api/v1/admin/users", headers=admin_headers,
                    json={"email": "newop@rackmon.io", "password": "password1", "role": "operator"})
    assert r.status_code == 201
    login = client.post("/api/v1/auth/login",
                        json={"email": "newop@rackmon.io", "password": "password1"})
    assert login.status_code == 200


def test_create_user_duplicate(client: TestClient, admin_headers: dict):
    payload = {"email": "dup@rackmon.io", "password": "password1", "role": "viewer"}
    assert client.post("/api/v1/admin/users", headers=admin_headers, json=payload).status_code == 201
    assert client.post("/api/v1/admin/users", headers=admin_headers, json=payload).status_code == 409


def test_create_user_short_password(client: TestClient, admin_headers: dict):
    r = client.post("/api/v1/admin/users", headers=admin_headers,
                    json={"email": "x@rackmon.io", "password": "short", "role": "viewer"})
    assert r.status_code == 400


def test_cannot_delete_self(client: TestClient, admin_headers: dict):
    me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    r = client.delete(f"/api/v1/admin/users/{me['id']}", headers=admin_headers)
    assert r.status_code == 400


def test_update_user_role(client: TestClient, admin_headers: dict):
    uid = client.post("/api/v1/admin/users", headers=admin_headers,
                      json={"email": "up@rackmon.io", "password": "password1", "role": "viewer"}).json()["id"]
    r = client.patch(f"/api/v1/admin/users/{uid}", headers=admin_headers, json={"role": "operator"})
    assert r.status_code == 200
    assert r.json()["role"] == "operator"


def test_audit_log_records_actions(client: TestClient, admin_headers: dict, operator_headers: dict):
    # operator_headers fixture creates a user and logs in -> audit entries exist.
    r = client.get("/api/v1/admin/audit", headers=admin_headers)
    assert r.status_code == 200
    actions = {e["action"] for e in r.json()}
    assert "login" in actions or "user.create" in actions


def test_smtp_settings_roundtrip(client: TestClient, admin_headers: dict):
    r = client.put("/api/v1/admin/settings/smtp", headers=admin_headers, json={
        "host": "smtp.example.com", "port": 587, "user": "mailer",
        "password": "secretpw", "from_address": "alerts@example.com",
        "recipients": ["ops@example.com"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "smtp.example.com"
    assert body["has_password"] is True
    # Password must never be echoed back.
    assert "secretpw" not in r.text


def test_overview_shape(client: TestClient, admin_headers: dict, sample_device: dict):
    r = client.get("/api/v1/overview", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert "devices_total" in body
    assert "status_counts" in body
    assert set(body["status_counts"]) >= {"ok", "warning", "critical", "nodata", "maintenance"}


def test_delete_user_with_audit_history(client, admin_headers, db):
    """Deleting a user who has audit-log history (and other back-references)
    must succeed; historical rows survive with the actor nulled. Regression:
    used to 500 with 'FOREIGN KEY constraint failed'."""
    from app.models import AuditLog, User

    r = client.post("/api/v1/admin/users", headers=admin_headers,
                    json={"email": "todelete@example.com", "password": "password123", "role": "viewer"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]

    # give the user some audit history (as if they had acted)
    db.add(AuditLog(actor_id=uid, action="auth.login", target_type="user", target_id=str(uid)))
    db.commit()
    assert db.query(AuditLog).filter_by(actor_id=uid).count() >= 1

    d = client.delete(f"/api/v1/admin/users/{uid}", headers=admin_headers)
    assert d.status_code == 204, d.text

    # user gone; audit rows survive but the actor link is nulled (not deleted)
    assert db.get(User, uid) is None
    assert db.query(AuditLog).filter_by(actor_id=uid).count() == 0
    assert db.query(AuditLog).filter_by(action="auth.login").count() >= 1
