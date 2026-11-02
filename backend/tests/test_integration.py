"""Integration tests for background components.

These drive the real poller sweep (with the simulated collector), the retention
sweep, the notifier, and the realtime hub — the pieces that run outside the
request path in production.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import Alert, AlertState, Device, MetricPoint
from app.services import poller
from app.services.realtime import RealtimeHub
from app.services.scheduler import prune_raw_points


def test_poller_sweep_writes_points_and_populates_cache(
    client: TestClient, operator_headers: dict, db
):
    dev = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "poll-me", "ip": "10.0.0.50", "tags": ["compute"]},
    ).json()

    written, events = poller._poll_once_sync()
    assert written > 0
    # Latest-value cache now has entries for this device.
    assert len(poller.latest.for_device(dev["id"])) > 0
    # And points landed in the time-series table.
    count = db.scalar(
        select(MetricPoint).where(MetricPoint.device_id == dev["id"])
    )
    assert count is not None


def test_poller_fires_alert_end_to_end(client: TestClient, operator_headers: dict, db):
    dev = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "hot-node", "ip": "10.0.0.51", "tags": ["compute"]},
    ).json()
    # Always-true rule guarantees a deterministic firing through the poller.
    client.post(
        "/api/v1/rules", headers=operator_headers,
        json={"name": "always", "scope_type": "global", "metric": "temp_cpu",
              "operator": ">", "threshold": 0, "severity": "warning", "for_seconds": 0},
    )

    _, events = poller._poll_once_sync()
    assert any(e["state"] == "firing" for e in events)

    active = db.scalars(
        select(Alert).where(Alert.device_id == dev["id"],
                            Alert.state != AlertState.resolved.value)
    ).all()
    assert len(active) == 1


def test_retention_prunes_old_points(client: TestClient, operator_headers: dict, db):
    dev = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "old-data", "ip": "10.0.0.52"},
    ).json()
    metric = db.get(Device, dev["id"]).metrics[0]

    old_time = datetime.now(timezone.utc) - timedelta(days=999)
    db.add(MetricPoint(time=old_time, device_id=dev["id"], metric_id=metric.id,
                       value=1.0, status=0, latency_ms=1))
    db.commit()

    removed = prune_raw_points()
    assert removed >= 1


def test_notifier_records_console_notification(client: TestClient, operator_headers: dict, db):
    from app.models import AlertNotification
    from app.services import notifier

    dev = client.post(
        "/api/v1/devices", headers=operator_headers,
        json={"name": "notify", "ip": "10.0.0.53"},
    ).json()
    device = db.get(Device, dev["id"])
    alert = Alert(rule_id=None, device_id=device.id, metric="temp_cpu",
                  severity="critical", state=AlertState.firing.value, value=90.0,
                  message="temp_cpu > 80", started_at=datetime.now(timezone.utc))
    db.add(alert)
    db.commit()
    db.refresh(alert)

    notifier.dispatch(db, alert, device)
    db.commit()

    notes = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)
    ).all()
    assert any(n.channel == "console" and n.status == "sent" for n in notes)


def test_realtime_hub_publish_and_match():
    async def scenario():
        hub = RealtimeHub()
        sub = await hub.subscribe({"device.1.temp_cpu", "alerts"})
        # Matching topic is delivered.
        await hub.publish("device.1.temp_cpu", {"type": "metric", "value": 42})
        # Non-matching topic is not.
        await hub.publish("device.2.temp_cpu", {"type": "metric", "value": 99})
        msg = await asyncio.wait_for(sub.queue.get(), timeout=1)
        assert msg["value"] == 42
        assert sub.queue.empty()
        await hub.unsubscribe(sub)
        assert hub.client_count == 0

    asyncio.run(scenario())


def test_realtime_wildcard_subscription():
    async def scenario():
        hub = RealtimeHub()
        sub = await hub.subscribe(set())  # empty == all topics
        await hub.publish("anything.at.all", {"x": 1})
        msg = await asyncio.wait_for(sub.queue.get(), timeout=1)
        assert msg["x"] == 1

    asyncio.run(scenario())
