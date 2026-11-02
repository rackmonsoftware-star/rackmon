"""Runtime settings API: get/put whitelisted config groups."""
from __future__ import annotations


def test_get_empty_setting(client, admin_headers):
    r = client.get("/api/v1/admin/settings/report_schedule", headers=admin_headers)
    assert r.status_code == 200
    assert r.json() == {"key": "report_schedule", "value": {}}


def test_put_and_get_roundtrip(client, admin_headers):
    payload = {"value": {"enabled": True, "recipients": ["ops@corp.com"]}}
    put = client.put("/api/v1/admin/settings/report_schedule", headers=admin_headers, json=payload)
    assert put.status_code == 200
    got = client.get("/api/v1/admin/settings/report_schedule", headers=admin_headers).json()
    assert got["value"] == payload["value"]


def test_escalation_setting_editable(client, admin_headers):
    payload = {"value": {"enabled": True, "after_seconds": 300, "recipients": ["oncall@corp.com"]}}
    assert client.put("/api/v1/admin/settings/escalation", headers=admin_headers,
                      json=payload).status_code == 200


def test_unknown_setting_rejected(client, admin_headers):
    assert client.get("/api/v1/admin/settings/secret_thing", headers=admin_headers).status_code == 404
    assert client.put("/api/v1/admin/settings/secret_thing", headers=admin_headers,
                      json={"value": {}}).status_code == 404


def test_settings_require_admin(client, operator_headers):
    assert client.get("/api/v1/admin/settings/escalation").status_code == 401
    assert client.get("/api/v1/admin/settings/escalation", headers=operator_headers).status_code == 403
