"""API<->frontend contract guard.

The worst bug we hit was a silent drift between what the API serialized and what
the frontend read (samples were {time,value} but the UI read {t,v}). Unit tests
missed it because they fed the frontend shape directly. This test pins every
endpoint the UI consumes to the exact field names the UI reads, so that class of
bug can never be reintroduced without a red test.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Alert, MetricCatalog, MetricPoint


def _require(obj: dict, fields: set[str], where: str):
    missing = fields - set(obj.keys())
    assert not missing, f"{where}: API response is missing frontend fields {missing} (got {sorted(obj.keys())})"


def test_frontend_contract(client, admin_headers, db):
    H = admin_headers

    # --- create every entity the UI renders ---
    dev = client.post("/api/v1/devices", json={"name": "contract-dev", "ip": "10.9.0.1"}, headers=H).json()
    did = dev["id"]
    cat = db.scalars(select(MetricCatalog).where(MetricCatalog.device_id == did)).first()
    assert cat is not None
    now = datetime.now(timezone.utc)
    for i in range(4):
        db.add(MetricPoint(time=now - timedelta(minutes=i), device_id=did, metric_id=cat.id, value=30.0 + i, status=0))
    db.add(Alert(device_id=did, metric=cat.name, severity="warning", value=99.0, state="firing", message="hot"))
    db.commit()

    client.post("/api/v1/admin/users", json={"email": "c@corp.com", "password": "pw12345678", "role": "viewer"}, headers=H)
    key = client.post("/api/v1/admin/apikeys", json={"name": "contract-key"}, headers=H).json()
    client.post("/api/v1/annotations", json={"device_id": did, "text": "note"}, headers=H)
    client.post("/api/v1/rules", json={
        "name": "contract-rule", "scope_type": "global", "metric": cat.name,
        "operator": ">", "threshold": 70, "for_seconds": 60, "severity": "warning",
    }, headers=H)

    # --- Device ---
    d = client.get(f"/api/v1/devices/{did}", headers=H).json()
    _require(d, {"id", "name", "hostname", "ip", "snmp_version", "snmp_port", "vendor", "model",
                 "rack", "position_u", "size_u", "tags", "enabled", "has_community",
                 "in_maintenance", "created_at", "metrics"}, "Device")
    _require(d["metrics"][0], {"id", "name", "unit", "oid", "enabled", "poll_interval_s"}, "Device.metrics[]")

    # --- Metric series: THE field names that bit us ---
    from urllib.parse import quote
    frm = quote((now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    s = client.get(f"/api/v1/metrics?device_id={did}&metric={cat.name}&agg=raw&from={frm}", headers=H).json()
    _require(s, {"device_id", "metric", "unit", "aggregation", "samples"}, "MetricSeries")
    assert len(s["samples"]) >= 1, "series returned no samples for freshly-seeded data"
    _require(s["samples"][0], {"t", "v"}, "MetricSeries.samples[] (must be t/v, not time/value)")

    # --- Device status ---
    st = client.get("/api/v1/devices/status", headers=H).json()[0]
    _require(st, {"device", "status", "temperature", "last_seen", "firing_alerts"}, "DeviceStatus")
    _require(st["device"], {"id", "name", "ip"}, "DeviceStatus.device")

    # --- Overview ---
    ov = client.get("/api/v1/overview", headers=H).json()
    _require(ov, {"devices_total", "status_counts", "firing_alerts", "hottest",
                  "avg_temperature", "max_temperature"}, "Overview")

    # --- Alert ---
    al = client.get("/api/v1/alerts?active=false", headers=H).json()[0]
    _require(al, {"id", "rule_id", "device_id", "metric", "severity", "state", "value", "message",
                  "started_at", "ended_at", "acked_by", "acked_at", "ack_comment", "resolved_by",
                  "resolved_at", "resolve_comment", "snoozed_until"}, "Alert")

    # --- Alert rule ---
    ru = client.get("/api/v1/rules", headers=H).json()[0]
    _require(ru, {"id", "name", "scope_type", "scope_ref", "metric", "operator", "threshold",
                  "for_seconds", "severity", "enabled"}, "AlertRule")

    # --- User ---
    us = client.get("/api/v1/admin/users", headers=H).json()[0]
    _require(us, {"id", "email", "role", "is_active", "mfa_enabled", "last_login_at"}, "User")

    # --- API key (list + create) ---
    ak = client.get("/api/v1/admin/apikeys", headers=H).json()[0]
    _require(ak, {"id", "name", "prefix", "revoked", "last_used_at", "created_at"}, "ApiKey")
    _require(key, {"id", "name", "prefix", "key"}, "ApiKey(create) — must include plaintext 'key'")

    # --- Annotation ---
    an = client.get(f"/api/v1/annotations?device_id={did}", headers=H).json()[0]
    _require(an, {"id", "text", "at", "metric", "device_id"}, "Annotation")

    # --- Audit entry ---
    au = client.get("/api/v1/admin/audit", headers=H).json()[0]
    _require(au, {"id", "actor_id", "action", "target_type", "target_id", "ip", "created_at"}, "AuditEntry")
