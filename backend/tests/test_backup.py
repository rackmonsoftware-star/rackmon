"""Configuration backup / restore round-trip."""
from __future__ import annotations


def _seed_config(client, operator_headers) -> int:
    dev_id = client.post("/api/v1/devices", headers=operator_headers,
                         json={"name": "bkp-dev", "ip": "10.4.4.4", "rack": "RACK-Z"}).json()["id"]
    client.post("/api/v1/rules", headers=operator_headers, json={
        "name": "bkp-rule", "scope_type": "global", "metric": "temp_cpu",
        "operator": ">", "threshold": 70, "severity": "warning", "for_seconds": 0,
    })
    return dev_id


def test_backup_exports_devices_and_rules(client, admin_headers, operator_headers):
    _seed_config(client, operator_headers)
    b = client.get("/api/v1/admin/backup", headers=admin_headers)
    assert b.status_code == 200
    body = b.json()
    dev = next(d for d in body["devices"] if d["ip"] == "10.4.4.4")
    assert dev["metrics"] and any(m["name"] == "temp_cpu" for m in dev["metrics"])
    assert any(r["name"] == "bkp-rule" for r in body["rules"])


def test_restore_recreates_deleted_device(client, admin_headers, operator_headers):
    dev_id = _seed_config(client, operator_headers)
    backup = client.get("/api/v1/admin/backup", headers=admin_headers).json()

    # Remove the device, then restore from the backup.
    assert client.delete(f"/api/v1/devices/{dev_id}", headers=operator_headers).status_code == 204
    res = client.post("/api/v1/admin/restore", headers=admin_headers, json=backup)
    assert res.status_code == 200
    assert res.json()["devices_created"] == 1
    assert res.json()["rules_skipped"] >= 1  # rule still existed

    devs = client.get("/api/v1/devices", headers=operator_headers).json()
    restored = next(d for d in devs if d["ip"] == "10.4.4.4")
    assert any(m["name"] == "temp_cpu" for m in restored["metrics"])


def test_restore_skips_existing(client, admin_headers, operator_headers):
    _seed_config(client, operator_headers)
    backup = client.get("/api/v1/admin/backup", headers=admin_headers).json()
    res = client.post("/api/v1/admin/restore", headers=admin_headers, json=backup)
    assert res.json()["devices_skipped"] >= 1  # device already present


def test_backup_requires_admin(client, viewer_headers):
    assert client.get("/api/v1/admin/backup").status_code == 401
    assert client.get("/api/v1/admin/backup", headers=viewer_headers).status_code == 403
