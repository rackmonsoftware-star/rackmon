"""Notification dispatch.

Fase-1 channels are console (always available, so the platform is demoable with
no mail server) and SMTP email with STARTTLS/SSL. Additional channels (webhook,
Telegram, Slack, Teams) plug in behind the same ``send`` signature — the alert
engine does not know or care which channels exist.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import decrypt
from ..metrics_prom import NOTIFICATIONS_TOTAL
from ..models import Alert, AlertNotification, Device, Setting

log = logging.getLogger("rackmon.notifier")


def _smtp_config(db: Session) -> dict:
    """Effective SMTP config: DB settings override environment defaults."""
    s = get_settings()
    cfg = {
        "host": s.smtp_host,
        "port": s.smtp_port,
        "user": s.smtp_user,
        "password": s.smtp_password,
        "use_tls": s.smtp_use_tls,
        "use_ssl": s.smtp_use_ssl,
        "from_address": s.smtp_from,
        "recipients": list(s.alert_default_recipients),
    }
    row = db.get(Setting, "smtp")
    if row and row.value:
        v = dict(row.value)
        pw_enc = v.pop("password_enc", None)
        cfg.update({k: val for k, val in v.items() if val is not None})
        if pw_enc:
            cfg["password"] = decrypt(pw_enc)
    return cfg


def _render(alert: Alert, device: Device) -> tuple[str, str]:
    s = get_settings()
    sev = alert.severity.upper()
    link = f"{s.public_base_url}/devices/{device.id}"
    subject = f"[RackMon][{sev}] {device.name} — {alert.metric} = {alert.value}"
    body = (
        f"A RackMon alert is {alert.state.upper()}.\n\n"
        f"Device:    {device.name} ({device.ip})\n"
        f"Rack:      {device.rack or '-'} U{device.position_u or '-'}\n"
        f"Metric:    {alert.metric}\n"
        f"Value:     {alert.value}\n"
        f"Severity:  {alert.severity}\n"
        f"Message:   {alert.message}\n"
        f"Started:   {alert.started_at.isoformat()}\n\n"
        f"Open device: {link}\n"
    )
    return subject, body


def _send_email(cfg: dict, subject: str, body: str, recipients: list[str],
                attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_address"]
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="rackmon.local")
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Priority"] = "1" if "CRITICAL" in subject else "3"
    msg.set_content(body)
    for filename, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=filename)

    host, port = cfg["host"], int(cfg["port"])
    if cfg.get("use_ssl"):
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as smtp:
            if cfg.get("user"):
                smtp.login(cfg["user"], cfg.get("password") or "")
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            if cfg.get("use_tls"):
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if cfg.get("user"):
                smtp.login(cfg["user"], cfg.get("password") or "")
            smtp.send_message(msg)


def _channels_config(db: Session) -> dict:
    """Effective extra-channel config: DB 'channels' setting overrides env."""
    s = get_settings()
    cfg = {
        "webhook_url": s.alert_webhook_url,
        "slack_webhook_url": s.slack_webhook_url,
        "teams_webhook_url": s.teams_webhook_url,
        "telegram_token": s.telegram_bot_token,
        "telegram_chat_id": s.telegram_chat_id,
    }
    row = db.get(Setting, "channels")
    if row and row.value:
        v = dict(row.value)
        tok_enc = v.pop("telegram_token_enc", None)
        cfg.update({k: val for k, val in v.items() if val is not None})
        if tok_enc:
            cfg["telegram_token"] = decrypt(tok_enc)
    return cfg


def _post_json(url: str, payload: dict, timeout: float = 10.0) -> None:  # pragma: no cover - network
    """POST JSON to a URL. Isolated so tests can monkeypatch it."""
    resp = httpx.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()


def _send_webhook(url: str, alert: Alert, device: Device) -> None:
    s = get_settings()
    _post_json(url, {
        "event": "alert",
        "state": alert.state,
        "severity": alert.severity,
        "device": {"id": device.id, "name": device.name, "ip": device.ip,
                   "rack": device.rack, "position_u": device.position_u},
        "metric": alert.metric,
        "value": alert.value,
        "message": alert.message,
        "started_at": alert.started_at.isoformat(),
        "link": f"{s.public_base_url}/devices/{device.id}",
    })


def _send_text_webhook(url: str, subject: str, body: str) -> None:
    # Slack and Microsoft Teams both accept a simple {"text": ...} incoming webhook.
    _post_json(url, {"text": f"*{subject}*\n{body}"})


def _send_telegram(token: str, chat_id: str, subject: str, body: str) -> None:
    _post_json(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": f"{subject}\n\n{body}"},
    )


def _record(db: Session, alert: Alert, channel: str, target: str,
            fn) -> None:
    """Run a sender, recording an AlertNotification row and metric either way."""
    status, detail = "sent", None
    try:
        fn()
    except Exception as exc:
        status, detail = "failed", str(exc)[:500]
        log.warning("%s notification failed: %s", channel, exc)
    db.add(AlertNotification(alert_id=alert.id, channel=channel,
                             target=target, status=status, detail=detail))
    NOTIFICATIONS_TOTAL.labels(channel=channel, status=status).inc()


def dispatch(db: Session, alert: Alert, device: Device) -> None:
    """Send notifications for an alert transition and record them. Caller commits."""
    subject, body = _render(alert, device)
    cfg = _smtp_config(db)
    recipients = cfg.get("recipients") or []

    # Console channel is always on — the operational fallback.
    log.info("ALERT %s | %s", alert.state, subject)
    db.add(
        AlertNotification(
            alert_id=alert.id, channel="console", target="log",
            status="sent", detail=subject,
        )
    )
    NOTIFICATIONS_TOTAL.labels(channel="console", status="sent").inc()

    if cfg.get("host") and recipients:
        status = "sent"
        detail = None
        try:
            _send_email(cfg, subject, body, recipients)
        except Exception as exc:  # pragma: no cover - network dependent
            status = "failed"
            detail = str(exc)
            log.warning("SMTP send failed: %s", exc)
        db.add(
            AlertNotification(
                alert_id=alert.id, channel="email",
                target=", ".join(recipients), status=status, detail=detail,
            )
        )
        NOTIFICATIONS_TOTAL.labels(channel="email", status=status).inc()

    # Extra channels (all optional; each isolated so one failure can't block others).
    ch = _channels_config(db)
    if ch.get("webhook_url"):
        _record(db, alert, "webhook", ch["webhook_url"],
                lambda: _send_webhook(ch["webhook_url"], alert, device))
    if ch.get("slack_webhook_url"):
        _record(db, alert, "slack", "slack",
                lambda: _send_text_webhook(ch["slack_webhook_url"], subject, body))
    if ch.get("teams_webhook_url"):
        _record(db, alert, "teams", "teams",
                lambda: _send_text_webhook(ch["teams_webhook_url"], subject, body))
    if ch.get("telegram_token") and ch.get("telegram_chat_id"):
        _record(db, alert, "telegram", str(ch["telegram_chat_id"]),
                lambda: _send_telegram(ch["telegram_token"], ch["telegram_chat_id"], subject, body))

    # Plugin channels (registered via app.plugins). Isolated like built-ins.
    from ..plugins import channel_plugins
    for pname, pfn in channel_plugins().items():
        _record(db, alert, f"plugin:{pname}", pname,
                lambda pfn=pfn, pname=pname: pfn(alert, device, ch))


def send_test_email(db: Session, to: str) -> None:  # pragma: no cover - network dependent
    cfg = _smtp_config(db)
    if not cfg.get("host"):
        raise ValueError("SMTP host is not configured")
    now = datetime.now(timezone.utc).isoformat()
    _send_email(cfg, "[RackMon] Test email", f"RackMon SMTP test at {now}.", [to])
