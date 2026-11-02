from fastapi.testclient import TestClient


def test_create_device_default_metrics(client: TestClient, operator_headers: dict):
    r = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "n1", "ip": "10.0.0.9"},
    )
    assert r.status_code == 201
    body = r.json()
    assert len(body["metrics"]) >= 1  # default catalog applied
    assert body["has_community"] is False


def test_create_device_stores_community_encrypted(client: TestClient, operator_headers: dict, db):
    r = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "n2", "ip": "10.0.0.10", "snmp_community": "topsecret"},
    )
    assert r.status_code == 201
    assert r.json()["has_community"] is True
    # The plaintext community must never be returned by the API.
    assert "topsecret" not in r.text

    from app.crypto import decrypt
    from app.models import Device

    dev = db.get(Device, r.json()["id"])
    assert dev.snmp_community_enc is not None
    assert dev.snmp_community_enc != "topsecret"
    assert decrypt(dev.snmp_community_enc) == "topsecret"


def test_viewer_cannot_create(client: TestClient, viewer_headers: dict):
    r = client.post("/api/v1/devices", headers=viewer_headers, json={"name": "x", "ip": "1.1.1.1"})
    assert r.status_code == 403


def test_list_and_filter(client: TestClient, operator_headers: dict, sample_device: dict):
    r = client.get("/api/v1/devices", headers=operator_headers)
    assert r.status_code == 200
    assert any(d["id"] == sample_device["id"] for d in r.json())

    r = client.get("/api/v1/devices?tag=compute", headers=operator_headers)
    assert all("compute" in d["tags"] for d in r.json())

    r = client.get("/api/v1/devices?q=test-node", headers=operator_headers)
    assert any(d["id"] == sample_device["id"] for d in r.json())

    r = client.get("/api/v1/devices?rack=RACK-T", headers=operator_headers)
    assert all(d["rack"] == "RACK-T" for d in r.json())


def test_get_update_delete(client: TestClient, operator_headers: dict, sample_device: dict):
    did = sample_device["id"]
    assert client.get(f"/api/v1/devices/{did}", headers=operator_headers).status_code == 200

    r = client.patch(f"/api/v1/devices/{did}", headers=operator_headers,
                     json={"name": "renamed", "enabled": False})
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"
    assert r.json()["enabled"] is False

    assert client.delete(f"/api/v1/devices/{did}", headers=operator_headers).status_code == 204
    assert client.get(f"/api/v1/devices/{did}", headers=operator_headers).status_code == 404


def test_get_missing_device(client: TestClient, operator_headers: dict):
    assert client.get("/api/v1/devices/999999", headers=operator_headers).status_code == 404


def test_invalid_position_rejected(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/devices", headers=operator_headers,
                    json={"name": "n", "ip": "1.2.3.4", "position_u": 999})
    assert r.status_code == 422


def test_maintenance_window(client: TestClient, operator_headers: dict, sample_device: dict):
    did = sample_device["id"]
    r = client.post(f"/api/v1/devices/{did}/maintenance", headers=operator_headers,
                    json={"minutes": 30})
    assert r.status_code == 200
    assert r.json()["in_maintenance"] is True

    r = client.delete(f"/api/v1/devices/{did}/maintenance", headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["in_maintenance"] is False


def test_duplicate_metric_rejected(client: TestClient, operator_headers: dict):
    r = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={
            "name": "dupe", "ip": "10.0.0.11",
            "metrics": [
                {"name": "temp_cpu", "unit": "C"},
                {"name": "temp_cpu", "unit": "C"},
            ],
        },
    )
    assert r.status_code == 400


def test_delete_device_with_children(client, operator_headers, sample_device, db):
    """Deleting a device that has annotations, alerts and metric points must
    succeed. Regression: it used to 500 with 'FOREIGN KEY constraint failed'
    because annotations reference the device and were not cleaned up."""
    from datetime import datetime, timezone

    from app.models import Alert, Annotation, MetricPoint

    did = sample_device["id"]
    now = datetime.now(timezone.utc)
    db.add(Annotation(device_id=did, text="replaced fan here"))
    db.add(Alert(device_id=did, metric="temp_cpu", severity="warning", value=99.0))
    db.add(MetricPoint(device_id=did, metric_id=1, value=42.0, time=now))
    db.commit()

    r = client.delete(f"/api/v1/devices/{did}", headers=operator_headers)
    assert r.status_code == 204, r.text

    # device and all its child rows are gone (no orphans, no FK failure)
    assert db.query(Annotation).filter_by(device_id=did).count() == 0
    assert db.query(Alert).filter_by(device_id=did).count() == 0
    assert db.query(MetricPoint).filter_by(device_id=did).count() == 0


def test_device_input_validation(client, operator_headers):
    """The API must reject empty/whitespace names and blank/space-containing IPs
    (the UI blocks these, but the API must be defensive for integrations too)."""
    def mk(**over):
        body = {"name": "ok-name", "ip": "10.0.0.9", "snmp_version": "2c"}
        body.update(over)
        return client.post("/api/v1/devices", headers=operator_headers, json=body)

    assert mk(name="").status_code == 422
    assert mk(name="   ").status_code == 422
    assert mk(ip="").status_code == 422
    assert mk(ip="   ").status_code == 422
    assert mk(ip="10.0.0.1 extra").status_code == 422  # space in host
    # a valid IP and a valid hostname are both accepted
    assert mk(name="  trimmed  ", ip="10.0.0.7").status_code == 201
    assert mk(name="host-dev", ip="switch-01.corp.local").status_code == 201
