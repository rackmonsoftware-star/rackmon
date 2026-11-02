"""Plugin system: registration, dispatch invocation, isolation, and loading."""
from __future__ import annotations

from sqlalchemy import select

from app import plugins
from app.models import Alert, AlertNotification, Device, utcnow
from app.services import notifier


def _alert(db) -> tuple[Alert, Device]:
    dev = Device(name="plug-dev", ip="10.11.11.11", snmp_version="2c")
    db.add(dev)
    db.commit()
    db.refresh(dev)
    a = Alert(device_id=dev.id, metric="temp_cpu", severity="warning", state="firing",
              value=80.0, message="hot", started_at=utcnow())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a, dev


def test_registered_plugin_is_invoked(db):
    calls: list = []

    @plugins.register_channel("testchan")
    def _p(alert, device, config):
        calls.append((alert.id, device.id))

    alert, dev = _alert(db)
    notifier.dispatch(db, alert, dev)
    db.commit()

    assert calls == [(alert.id, dev.id)]
    rows = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)).all()
    by_channel = {r.channel: r.status for r in rows}
    assert by_channel.get("plugin:testchan") == "sent"


def test_failing_plugin_is_isolated(db):
    @plugins.register_channel("boom")
    def _p(alert, device, config):
        raise RuntimeError("kaboom")

    alert, dev = _alert(db)
    notifier.dispatch(db, alert, dev)  # must not raise
    db.commit()

    rows = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)).all()
    by_channel = {r.channel: r.status for r in rows}
    assert by_channel.get("plugin:boom") == "failed"
    assert by_channel.get("console") == "sent"  # built-in unaffected


def test_load_plugins_registers_example():
    assert "pagerduty" not in plugins.channel_plugins()
    loaded = plugins.load_plugins(["app.plugins.examples.pagerduty"])
    assert "app.plugins.examples.pagerduty" in loaded
    assert "pagerduty" in plugins.channel_plugins()


def test_clear_registry():
    @plugins.register_channel("temp")
    def _p(alert, device, config):
        pass

    assert "temp" in plugins.channel_plugins()
    plugins.clear_channel_plugins()
    assert plugins.channel_plugins() == {}
