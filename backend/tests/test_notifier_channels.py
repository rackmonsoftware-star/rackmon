"""Multi-channel notification dispatch — network calls are monkeypatched."""
from __future__ import annotations

from sqlalchemy import select

from app.models import Alert, AlertNotification, Device, Setting, utcnow
from app.services import notifier


def _make_alert(db) -> tuple[Alert, Device]:
    dev = Device(name="chan-node", ip="10.9.9.9", snmp_version="2c")
    db.add(dev)
    db.commit()
    db.refresh(dev)
    alert = Alert(
        device_id=dev.id, metric="temp_cpu", severity="warning", state="firing",
        value=81.5, message="too hot", started_at=utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert, dev


def _configure_channels(db) -> None:
    db.add(Setting(key="channels", value={
        "webhook_url": "https://hook.example/ingest",
        "slack_webhook_url": "https://hooks.slack.com/services/T/B/X",
        "teams_webhook_url": "https://outlook.office.com/webhook/abc",
        "telegram_token": "BOT123",
        "telegram_chat_id": "555",
    }))
    db.commit()


def test_all_channels_dispatched(db, monkeypatch):
    _configure_channels(db)
    alert, dev = _make_alert(db)

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(notifier, "_post_json",
                        lambda url, payload, timeout=10.0: calls.append((url, payload)))

    notifier.dispatch(db, alert, dev)
    db.commit()

    urls = [u for u, _ in calls]
    assert "https://hook.example/ingest" in urls
    assert "https://hooks.slack.com/services/T/B/X" in urls
    assert "https://outlook.office.com/webhook/abc" in urls
    assert any("api.telegram.org/botBOT123/sendMessage" in u for u in urls)

    # Slack/Teams use a text payload; webhook carries structured data.
    slack_payload = next(p for u, p in calls if "slack" in u)
    assert "text" in slack_payload
    webhook_payload = next(p for u, p in calls if u.endswith("/ingest"))
    assert webhook_payload["metric"] == "temp_cpu"
    assert webhook_payload["device"]["id"] == dev.id

    rows = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)
    ).all()
    by_channel = {r.channel: r.status for r in rows}
    for ch in ("console", "webhook", "slack", "teams", "telegram"):
        assert by_channel.get(ch) == "sent", f"{ch}: {by_channel}"


def test_one_channel_failure_is_isolated(db, monkeypatch):
    _configure_channels(db)
    alert, dev = _make_alert(db)

    def flaky(url, payload, timeout=10.0):
        if "slack" in url:
            raise RuntimeError("slack 500")

    monkeypatch.setattr(notifier, "_post_json", flaky)

    # Must not raise even though one channel fails.
    notifier.dispatch(db, alert, dev)
    db.commit()

    rows = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)
    ).all()
    by_channel = {r.channel: r.status for r in rows}
    assert by_channel["slack"] == "failed"
    assert by_channel["webhook"] == "sent"
    assert by_channel["teams"] == "sent"
    assert by_channel["telegram"] == "sent"


def test_no_channels_configured_only_console(db, monkeypatch):
    alert, dev = _make_alert(db)
    called = []
    monkeypatch.setattr(notifier, "_post_json",
                        lambda *a, **k: called.append(a))

    notifier.dispatch(db, alert, dev)
    db.commit()

    assert called == []  # nothing posted
    rows = db.scalars(
        select(AlertNotification).where(AlertNotification.alert_id == alert.id)
    ).all()
    assert [r.channel for r in rows] == ["console"]
