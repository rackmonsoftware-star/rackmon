from fastapi.testclient import TestClient


def _rule(**over):
    base = {
        "name": "temp warn", "scope_type": "global", "metric": "temp_cpu",
        "operator": ">", "threshold": 70, "severity": "warning",
    }
    base.update(over)
    return base


def test_create_and_list_rule(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/rules", headers=operator_headers, json=_rule())
    assert r.status_code == 201
    rid = r.json()["id"]
    assert any(x["id"] == rid for x in client.get("/api/v1/rules", headers=operator_headers).json())


def test_device_scope_requires_valid_ref(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/rules", headers=operator_headers,
                    json=_rule(scope_type="device", scope_ref="999999"))
    assert r.status_code == 400


def test_device_scope_valid(client: TestClient, operator_headers: dict, sample_device: dict):
    r = client.post("/api/v1/rules", headers=operator_headers,
                    json=_rule(scope_type="device", scope_ref=str(sample_device["id"])))
    assert r.status_code == 201


def test_tag_scope_requires_ref(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/rules", headers=operator_headers,
                    json=_rule(scope_type="tag", scope_ref=None))
    assert r.status_code == 400


def test_update_and_delete_rule(client: TestClient, operator_headers: dict):
    rid = client.post("/api/v1/rules", headers=operator_headers, json=_rule()).json()["id"]
    r = client.patch(f"/api/v1/rules/{rid}", headers=operator_headers, json={"threshold": 85})
    assert r.status_code == 200
    assert r.json()["threshold"] == 85
    assert client.delete(f"/api/v1/rules/{rid}", headers=operator_headers).status_code == 204
    assert client.get(f"/api/v1/rules/{rid}", headers=operator_headers).status_code == 404


def test_invalid_operator_rejected(client: TestClient, operator_headers: dict):
    r = client.post("/api/v1/rules", headers=operator_headers, json=_rule(operator="=>"))
    assert r.status_code == 422


def test_viewer_cannot_create_rule(client: TestClient, viewer_headers: dict):
    assert client.post("/api/v1/rules", headers=viewer_headers, json=_rule()).status_code == 403


def test_delete_rule_with_alerts(client, operator_headers, db):
    """Deleting a rule that has produced alerts must succeed (204); the alerts
    survive with rule_id nulled. Regression: used to 500 on a FK constraint."""
    from app.models import Alert

    r = client.post("/api/v1/rules", headers=operator_headers, json=_rule())
    assert r.status_code == 201
    rid = r.json()["id"]
    db.add(Alert(device_id=1, rule_id=rid, metric="temp_cpu", severity="warning", value=88.0))
    db.commit()
    assert db.query(Alert).filter_by(rule_id=rid).count() == 1

    d = client.delete(f"/api/v1/rules/{rid}", headers=operator_headers)
    assert d.status_code == 204, d.text
    assert db.query(Alert).filter_by(rule_id=rid).count() == 0  # detached
    assert db.query(Alert).filter_by(metric="temp_cpu", value=88.0).count() == 1  # survives
