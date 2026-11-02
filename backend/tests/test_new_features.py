"""Tests for the newly added self-service and management endpoints."""
import pyotp

from app.models import Alert


def test_change_password(client, admin_headers):
    # wrong current password rejected
    r = client.post("/api/v1/auth/change-password",
                    json={"current_password": "wrong", "new_password": "newpass12345"},
                    headers=admin_headers)
    assert r.status_code == 400
    # correct current password accepted
    r = client.post("/api/v1/auth/change-password",
                    json={"current_password": "admin12345", "new_password": "newpass12345"},
                    headers=admin_headers)
    assert r.status_code == 200
    # can log in with the new password
    r = client.post("/api/v1/auth/login", json={"email": "admin@rackmon.io", "password": "newpass12345"})
    assert r.status_code == 200


def test_mfa_enrollment_flow(client, admin_headers):
    setup = client.post("/api/v1/auth/mfa/setup", headers=admin_headers).json()
    assert "secret" in setup and "otpauth_url" in setup
    secret = setup["secret"]
    # wrong code rejected
    bad = client.post("/api/v1/auth/mfa/enable", json={"secret": secret, "otp": "000000"}, headers=admin_headers)
    assert bad.status_code == 400
    # correct code enables MFA
    code = pyotp.TOTP(secret).now()
    ok = client.post("/api/v1/auth/mfa/enable", json={"secret": secret, "otp": code}, headers=admin_headers)
    assert ok.status_code == 200 and ok.json()["mfa_enabled"] is True
    # disable requires the account password
    assert client.post("/api/v1/auth/mfa/disable", json={"password": "nope"}, headers=admin_headers).status_code == 400
    off = client.post("/api/v1/auth/mfa/disable", json={"password": "admin12345"}, headers=admin_headers)
    assert off.status_code == 200 and off.json()["mfa_enabled"] is False


def test_annotation_edit(client, admin_headers):
    dev = client.post("/api/v1/devices", json={"name": "annot-dev", "ip": "10.5.0.1"}, headers=admin_headers).json()
    ann = client.post("/api/v1/annotations",
                      json={"device_id": dev["id"], "text": "before"}, headers=admin_headers).json()
    r = client.patch(f"/api/v1/annotations/{ann['id']}", json={"text": "after"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["text"] == "after"


def test_alert_snooze(client, admin_headers, db):
    a = Alert(device_id=1, metric="temp_cpu", severity="warning", value=50.0, state="firing", message="hot")
    db.add(a)
    db.commit()
    db.refresh(a)
    r = client.post(f"/api/v1/alerts/{a.id}/snooze?minutes=30", headers=admin_headers)
    assert r.status_code == 200 and r.json()["snoozed_until"] is not None
    r2 = client.delete(f"/api/v1/alerts/{a.id}/snooze", headers=admin_headers)
    assert r2.status_code == 200 and r2.json()["snoozed_until"] is None


def test_apikey_rename(client, admin_headers):
    key = client.post("/api/v1/admin/apikeys", json={"name": "old-name"}, headers=admin_headers).json()
    r = client.patch(f"/api/v1/admin/apikeys/{key['id']}", json={"name": "new-name"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["name"] == "new-name"


def test_user_email_edit(client, admin_headers):
    u = client.post("/api/v1/admin/users",
                    json={"email": "e1@corp.com", "password": "pw12345678", "role": "viewer"},
                    headers=admin_headers).json()
    r = client.patch(f"/api/v1/admin/users/{u['id']}", json={"email": "e2@corp.com"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["email"] == "e2@corp.com"


def test_report_csv_export(client, admin_headers):
    r = client.get("/api/v1/reports/adhoc?fmt=csv", headers=admin_headers)
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "device" in r.text.splitlines()[0]


def test_metrics_sample_contract_is_t_v(client, admin_headers, db):
    """Charts read s.t / s.v — guard that the API never regresses to time/value."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.models import MetricCatalog, MetricPoint

    dev = client.post("/api/v1/devices", json={"name": "tvdev", "ip": "10.7.0.9"}, headers=admin_headers).json()
    cat = db.scalars(select(MetricCatalog).where(MetricCatalog.device_id == dev["id"])).first()
    assert cat is not None
    now = datetime.now(timezone.utc)
    for i in range(5):
        db.add(MetricPoint(time=now - timedelta(minutes=i), device_id=dev["id"], metric_id=cat.id, value=30.0 + i, status=0))
    db.commit()
    r = client.get(f"/api/v1/metrics?device_id={dev['id']}&metric={cat.name}&agg=raw", headers=admin_headers)
    assert r.status_code == 200
    samples = r.json()["samples"]
    assert len(samples) >= 1
    assert "t" in samples[0] and "v" in samples[0]
    assert "time" not in samples[0] and "value" not in samples[0]
