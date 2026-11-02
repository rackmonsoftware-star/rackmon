from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models import Alert, AlertState


def _make_alert(db, device_id: int, state=AlertState.firing.value, severity="critical") -> int:
    alert = Alert(
        rule_id=None, device_id=device_id, metric="temp_cpu", severity=severity,
        state=state, value=88.0, message="temp_cpu > 80 (actual 88)",
        started_at=datetime.now(timezone.utc),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert.id


def test_list_alerts(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _make_alert(db, sample_device["id"])
    r = client.get("/api/v1/alerts?active=true", headers=operator_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_filter_by_severity(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _make_alert(db, sample_device["id"], severity="critical")
    _make_alert(db, sample_device["id"], severity="warning")
    r = client.get("/api/v1/alerts?severity=warning", headers=operator_headers)
    assert all(a["severity"] == "warning" for a in r.json())


def test_ack_requires_comment(client: TestClient, db, sample_device: dict, operator_headers: dict):
    aid = _make_alert(db, sample_device["id"])
    # Empty comment fails validation.
    r = client.post(f"/api/v1/alerts/{aid}/ack", headers=operator_headers, json={"comment": ""})
    assert r.status_code == 422


def test_ack_then_resolve(client: TestClient, db, sample_device: dict, operator_headers: dict):
    aid = _make_alert(db, sample_device["id"])
    r = client.post(f"/api/v1/alerts/{aid}/ack", headers=operator_headers,
                    json={"comment": "looking into it"})
    assert r.status_code == 200
    assert r.json()["state"] == "acked"
    assert r.json()["ack_comment"] == "looking into it"

    r = client.post(f"/api/v1/alerts/{aid}/resolve", headers=operator_headers,
                    json={"comment": "replaced fan"})
    assert r.status_code == 200
    assert r.json()["state"] == "resolved"
    assert r.json()["resolved_at"] is not None


def test_cannot_resolve_twice(client: TestClient, db, sample_device: dict, operator_headers: dict):
    aid = _make_alert(db, sample_device["id"])
    client.post(f"/api/v1/alerts/{aid}/resolve", headers=operator_headers, json={"comment": "x"})
    r = client.post(f"/api/v1/alerts/{aid}/resolve", headers=operator_headers, json={"comment": "y"})
    assert r.status_code == 409


def test_viewer_cannot_ack(client: TestClient, db, sample_device: dict, viewer_headers: dict):
    aid = _make_alert(db, sample_device["id"])
    r = client.post(f"/api/v1/alerts/{aid}/ack", headers=viewer_headers, json={"comment": "x"})
    assert r.status_code == 403


def test_history_endpoint(client: TestClient, db, sample_device: dict, operator_headers: dict):
    _make_alert(db, sample_device["id"], state=AlertState.resolved.value)
    r = client.get("/api/v1/alerts/history", headers=operator_headers)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_ack_missing_alert(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/alerts/999999/ack", headers=operator_headers, json={"comment": "x"})
    assert r.status_code == 404
