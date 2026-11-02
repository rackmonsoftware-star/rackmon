"""Per-vendor device templates: listing and applying."""
from __future__ import annotations


def test_list_templates(client, operator_headers):
    r = client.get("/api/v1/templates", headers=operator_headers)
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert {"generic-server", "dell-idrac", "hpe-ilo", "apc-pdu"} <= names
    dell = next(t for t in r.json() if t["name"] == "dell-idrac")
    assert dell["vendor"] == "Dell" and len(dell["metrics"]) >= 2


def test_apply_template_creates_device_with_metrics(client, operator_headers):
    r = client.post("/api/v1/templates/apply", headers=operator_headers,
                    json={"template": "dell-idrac", "name": "srv-01", "ip": "10.3.3.3"})
    assert r.status_code == 201
    dev = r.json()
    assert dev["vendor"] == "Dell"
    assert any(m["name"] == "temp_inlet" for m in dev["metrics"])


def test_apply_unknown_template_404(client, operator_headers):
    r = client.post("/api/v1/templates/apply", headers=operator_headers,
                    json={"template": "nope", "name": "x", "ip": "10.3.3.4"})
    assert r.status_code == 404


def test_apply_duplicate_ip_409(client, operator_headers):
    client.post("/api/v1/devices", headers=operator_headers,
                json={"name": "taken", "ip": "10.3.3.5"})
    r = client.post("/api/v1/templates/apply", headers=operator_headers,
                    json={"template": "generic-server", "name": "dup", "ip": "10.3.3.5"})
    assert r.status_code == 409


def test_templates_require_operator(client, viewer_headers):
    assert client.get("/api/v1/templates").status_code == 401
    assert client.get("/api/v1/templates", headers=viewer_headers).status_code == 403
