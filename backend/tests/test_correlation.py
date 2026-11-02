"""Alert correlation: group active alerts by rack into incidents."""
from __future__ import annotations

from app.models import Alert, utcnow


def _device(client, headers, name, ip, rack) -> int:
    return client.post("/api/v1/devices", headers=headers,
                       json={"name": name, "ip": ip, "rack": rack}).json()["id"]


def _fire(db, device_id, severity="warning", state="firing") -> None:
    db.add(Alert(device_id=device_id, metric="temp_cpu", severity=severity,
                 state=state, value=80.0, message="hot", started_at=utcnow()))
    db.commit()


def test_correlations_group_by_rack(client, admin_headers, operator_headers, db):
    a1 = _device(client, operator_headers, "a1", "10.5.5.1", "RACK-A")
    a2 = _device(client, operator_headers, "a2", "10.5.5.2", "RACK-A")
    b1 = _device(client, operator_headers, "b1", "10.5.5.3", "RACK-B")
    _fire(db, a1)
    _fire(db, a2)
    _fire(db, b1)  # alone in RACK-B -> singleton, not a correlation

    r = client.get("/api/v1/alerts/correlations", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["grouped_incidents"] == 1
    assert body["singletons"] == 1
    group = body["correlations"][0]
    assert group["rack"] == "RACK-A"
    assert group["count"] == 2


def test_correlations_ignore_resolved(client, admin_headers, operator_headers, db):
    a1 = _device(client, operator_headers, "a1", "10.5.6.1", "RACK-C")
    a2 = _device(client, operator_headers, "a2", "10.5.6.2", "RACK-C")
    _fire(db, a1, state="firing")
    _fire(db, a2, state="resolved")  # resolved should not count

    body = client.get("/api/v1/alerts/correlations", headers=admin_headers).json()
    assert body["grouped_incidents"] == 0  # only one active alert in the rack


def test_correlations_require_auth(client):
    assert client.get("/api/v1/alerts/correlations").status_code == 401
