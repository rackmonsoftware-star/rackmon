"""Alert escalation (Fase 2).

If an alert stays in the ``firing`` state (not acknowledged/resolved) longer
than the configured threshold, notify the escalation recipients once and stamp
``escalated_at`` so it isn't escalated again. Runs on the scheduler; the logic
is unit-tested with SMTP monkeypatched.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, func

from ..config import get_settings
from ..metrics_prom import NOTIFICATIONS_TOTAL
from ..models import Alert, AlertNotification, AlertState, Device, Setting, ensure_aware, utcnow

log = logging.getLogger("rackmon.escalation")

# Cuántas veces se reintenta un escalado que no sale. Suficiente para
# sobrevivir a un SMTP que se reinicia; poco para no llenar la tabla si está
# mal configurado de raíz.
INTENTOS_MAXIMOS = 5


def _config(db) -> dict:
    s = get_settings()
    cfg = {
        "enabled": s.escalation_enabled,
        "after_seconds": s.escalate_after_seconds,
        "recipients": list(s.escalation_recipients),
    }
    row = db.get(Setting, "escalation")
    if row and row.value:
        cfg.update({k: v for k, v in row.value.items() if v is not None})
    return cfg


def escalate_pending(db, now=None) -> int:
    """Escalate firing alerts older than the threshold. Returns count escalated."""
    from . import notifier

    cfg = _config(db)
    now = now or utcnow()
    smtp = notifier._smtp_config(db)
    recipients = cfg["recipients"] or smtp.get("recipients") or []
    if not cfg["enabled"] or not recipients or not smtp.get("host"):
        return 0

    cutoff = now - timedelta(seconds=cfg["after_seconds"])
    pending = db.scalars(
        select(Alert).where(
            Alert.state == AlertState.firing.value,
            Alert.escalated_at.is_(None),
        )
    ).all()

    count = 0
    for a in pending:
        if ensure_aware(a.started_at) > cutoff:
            continue
        if a.snoozed_until is not None and ensure_aware(a.snoozed_until) > now:
            continue  # snoozed: suppress escalation until the snooze expires
        device = db.get(Device, a.device_id)
        _escalate_one(db, a, device, smtp, recipients, now)
        count += 1
    if count:
        db.commit()
        log.info("escalated %s alert(s)", count)
    return count


def _escalate_one(db, alert: Alert, device, smtp: dict, recipients: list[str], now) -> None:
    from . import notifier

    name = device.name if device else f"#{alert.device_id}"
    status, detail = "sent", None
    try:
        notifier._send_email(
            smtp,
            f"[RackMon][ESCALATED] {name} — {alert.message}",
            f"Alert #{alert.id} has been firing since "
            f"{ensure_aware(alert.started_at).isoformat()} without acknowledgement.",
            recipients,
        )
    except Exception as exc:  # pragma: no cover - defensive
        status, detail = "failed", str(exc)[:500]
        log.warning("escalation email failed: %s", exc)

    db.add(AlertNotification(alert_id=alert.id, channel="escalation",
                             target=",".join(recipients), status=status, detail=detail))
    NOTIFICATIONS_TOTAL.labels(channel="escalation", status=status).inc()

    # Solo se da por escalada si el correo SALIÓ. Antes se marcaba pasara lo que
    # pasara, así que un SMTP caído un minuto —o un rebote temporal— enterraba el
    # escalado para siempre: la alerta seguía sin reconocer, nadie más se enteraba
    # nunca, y el único rastro era una fila con status "failed" que nadie mira.
    # El escalado existe precisamente para el caso en que la primera notificación
    # no ha surtido efecto; que él mismo se rinda al primer fallo lo vacía.
    if status == "sent":
        alert.escalated_at = now
        return

    # Pero tampoco se reintenta eternamente: con un SMTP mal configurado se
    # escribiría una fila fallida en cada barrido, para siempre. Se cuenta lo ya
    # intentado y a los INTENTOS_MAXIMOS se deja estar, diciéndolo en el log.
    fallidos = db.scalar(
        select(func.count())
        .select_from(AlertNotification)
        .where(
            AlertNotification.alert_id == alert.id,
            AlertNotification.channel == "escalation",
            AlertNotification.status == "failed",
        )
    ) or 0
    if fallidos >= INTENTOS_MAXIMOS:
        alert.escalated_at = now
        log.warning(
            "escalado de la alerta #%s abandonado tras %s intentos fallidos: "
            "revisa la configuración de SMTP, porque nadie ha recibido este aviso",
            alert.id, fallidos,
        )
