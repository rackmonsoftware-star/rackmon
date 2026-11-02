"""Scheduled weekly PDF report (RF-45) — SMTP send is monkeypatched."""
from __future__ import annotations

from datetime import timedelta

from app.models import Setting, utcnow
from app.services import notifier, reports


def _configure_smtp(db) -> None:
    db.add(Setting(key="smtp", value={
        "host": "smtp.test", "port": 25, "from_address": "r@rackmon.io",
        "recipients": ["ops@rackmon.io"],
    }))
    db.commit()


def _enable_schedule(db) -> None:
    db.add(Setting(key="report_schedule",
                   value={"enabled": True, "recipients": ["ops@rackmon.io"]}))
    db.commit()


def _capture(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(notifier, "_send_email",
                        lambda cfg, subject, body, recipients, attachments=None:
                        calls.append((subject, recipients, attachments)))
    return calls


def test_send_weekly_report_attaches_pdf(db, monkeypatch):
    _configure_smtp(db)
    calls = _capture(monkeypatch)
    assert reports.send_weekly_report(db) is True
    assert len(calls) == 1
    _, recipients, attachments = calls[0]
    assert recipients == ["ops@rackmon.io"]
    fname, data, mime = attachments[0]
    assert fname.endswith(".pdf") and mime == "application/pdf"
    assert data[:4] == b"%PDF"


def test_send_weekly_report_skips_when_unconfigured(db, monkeypatch):
    calls = _capture(monkeypatch)  # no SMTP setting
    assert reports.send_weekly_report(db) is False
    assert calls == []


def test_maybe_send_respects_cadence(db, monkeypatch):
    _configure_smtp(db)
    _enable_schedule(db)
    calls = _capture(monkeypatch)

    t0 = utcnow()
    assert reports.maybe_send_weekly_report(db, now=t0) is True       # first send
    assert reports.maybe_send_weekly_report(db, now=t0) is False      # too soon
    assert reports.maybe_send_weekly_report(db, now=t0 + timedelta(days=8)) is True
    assert len(calls) == 2


def test_maybe_send_disabled_by_default(db, monkeypatch):
    _configure_smtp(db)  # SMTP ok, but schedule not enabled
    calls = _capture(monkeypatch)
    assert reports.maybe_send_weekly_report(db, now=utcnow()) is False
    assert calls == []
