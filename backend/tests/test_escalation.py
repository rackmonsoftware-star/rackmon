"""Alert escalation: notify on-call once for unacknowledged firing alerts."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Alert, AlertNotification, Device, Setting, utcnow
from app.services import escalation, notifier


def _setup(db, after_seconds=60) -> None:
    db.add(Setting(key="smtp", value={
        "host": "smtp.test", "port": 25, "from_address": "r@rackmon.io", "recipients": []}))
    db.add(Setting(key="escalation", value={
        "enabled": True, "after_seconds": after_seconds, "recipients": ["oncall@corp.com"]}))
    db.commit()


def _alert(db, age_seconds: int, state: str = "firing") -> Alert:
    dev = Device(name=f"d{age_seconds}", ip=f"10.20.0.{age_seconds % 250}", snmp_version="2c")
    db.add(dev)
    db.commit()
    db.refresh(dev)
    a = Alert(device_id=dev.id, metric="temp_cpu", severity="critical", state=state,
              value=90.0, message="too hot", started_at=utcnow() - timedelta(seconds=age_seconds))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_old_firing_alert_is_escalated(db, monkeypatch):
    _setup(db)
    calls: list = []
    monkeypatch.setattr(notifier, "_send_email",
                        lambda cfg, subj, body, recipients, attachments=None: calls.append((subj, recipients)))
    alert = _alert(db, age_seconds=120)

    assert escalation.escalate_pending(db, now=utcnow()) == 1
    db.refresh(alert)
    assert alert.escalated_at is not None
    assert calls and calls[0][1] == ["oncall@corp.com"]
    rows = db.scalars(select(AlertNotification).where(AlertNotification.alert_id == alert.id)).all()
    assert any(r.channel == "escalation" and r.status == "sent" for r in rows)

    # Not escalated twice.
    assert escalation.escalate_pending(db, now=utcnow()) == 0


def test_recent_alert_not_escalated(db, monkeypatch):
    _setup(db, after_seconds=300)
    monkeypatch.setattr(notifier, "_send_email", lambda *a, **k: None)
    _alert(db, age_seconds=30)  # younger than threshold
    assert escalation.escalate_pending(db, now=utcnow()) == 0


def test_acked_alert_not_escalated(db, monkeypatch):
    _setup(db)
    monkeypatch.setattr(notifier, "_send_email", lambda *a, **k: None)
    _alert(db, age_seconds=600, state="acked")  # already acknowledged
    assert escalation.escalate_pending(db, now=utcnow()) == 0


def test_disabled_by_default(db, monkeypatch):
    # SMTP present but no escalation Setting -> disabled via env default.
    db.add(Setting(key="smtp", value={"host": "smtp.test", "from_address": "r@x", "recipients": ["x@x"]}))
    db.commit()
    monkeypatch.setattr(notifier, "_send_email", lambda *a, **k: None)
    _alert(db, age_seconds=600)
    assert escalation.escalate_pending(db, now=utcnow()) == 0
