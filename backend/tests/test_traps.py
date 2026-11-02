"""SNMP trap handling: resolve source device, raise + notify an alert."""
from __future__ import annotations

from sqlalchemy import select

from app.models import Alert, AlertNotification
from app.services import traps


def _device(client, operator_headers, ip="10.8.8.8") -> int:
    return client.post("/api/v1/devices", headers=operator_headers,
                       json={"name": "trap-src", "ip": ip}).json()["id"]


def test_trap_from_known_device_creates_alert(client, operator_headers, db):
    dev_id = _device(client, operator_headers)
    alert = traps.handle_trap(db, "10.8.8.8", "1.3.6.1.6.3.1.1.5.3",
                              {"1.3.6.1.2.1.1.5.0": "core-switch"}, severity="critical")
    assert alert is not None
    assert alert.device_id == dev_id
    assert alert.metric == "snmp_trap"
    assert alert.severity == "critical"

    stored = db.scalars(select(Alert).where(Alert.metric == "snmp_trap")).all()
    assert len(stored) == 1
    # dispatch always records a console notification.
    notes = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)).all()
    assert any(n.channel == "console" for n in notes)


def test_trap_from_unknown_source_ignored(client, operator_headers, db):
    _device(client, operator_headers, ip="10.8.8.8")
    assert traps.handle_trap(db, "192.0.2.99", "1.3.6.1.6.3.1.1.5.1") is None
    assert db.scalars(select(Alert).where(Alert.metric == "snmp_trap")).all() == []


def test_trap_alert_appears_in_alerts_list(client, operator_headers, admin_headers, db):
    _device(client, operator_headers)
    traps.handle_trap(db, "10.8.8.8", "1.3.6.1.6.3.1.1.5.4")
    active = client.get("/api/v1/alerts?active=true", headers=admin_headers).json()
    assert any(a["metric"] == "snmp_trap" for a in active)
