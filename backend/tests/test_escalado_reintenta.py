"""Un escalado que no sale tiene que reintentarse.

El escalado existe para el caso en que la primera notificación no ha surtido
efecto: nadie ha reconocido la alerta en quince minutos, hay que avisar a otro.
Antes se marcaba `escalated_at` pasara lo que pasara con el correo, así que un
SMTP caído un minuto enterraba el aviso para siempre: la alerta seguía sin
reconocer, nadie más se enteraba nunca, y el único rastro era una fila con
status "failed" que no mira nadie.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Alert, AlertNotification, AlertRule, AlertState, Device
from app.services import escalation


@pytest.fixture()
def alerta_vieja(db):
    d = Device(name="sin-reconocer", ip="10.90.0.1", enabled=True)
    r = AlertRule(name="r", scope_type="global", metric="temp_inlet", operator=">",
                  threshold=32.0, for_seconds=0, severity="critical",
                  throttle_seconds=600, enabled=True)
    db.add_all([d, r]); db.commit()
    a = Alert(rule_id=r.id, device_id=d.id, metric="temp_inlet", severity="critical",
              state=AlertState.firing.value, message="temp_inlet > 32",
              value=40.0, started_at=datetime.now(timezone.utc) - timedelta(hours=2))
    db.add(a); db.commit()
    return a


def _configurar(monkeypatch, db, *, falla: bool):
    monkeypatch.setattr(escalation, "_config",
                        lambda _db: {"enabled": True, "recipients": ["jefe@corp.com"],
                                     "after_seconds": 900})
    from app.services import notifier
    monkeypatch.setattr(notifier, "_smtp_config",
                        lambda _db: {"host": "smtp.corp.com", "recipients": ["jefe@corp.com"]})

    def envio(*a, **k):
        if falla:
            raise RuntimeError("Connection refused")
    monkeypatch.setattr(notifier, "_send_email", envio)


def test_si_el_correo_falla_NO_se_da_por_escalada(db, monkeypatch, alerta_vieja):
    _configurar(monkeypatch, db, falla=True)

    escalation.escalate_pending(db)
    db.expire_all()

    assert alerta_vieja.escalated_at is None, (
        "se ha dado por escalada sin que el aviso llegara a nadie"
    )


def test_el_siguiente_barrido_lo_reintenta(db, monkeypatch, alerta_vieja):
    _configurar(monkeypatch, db, falla=True)
    escalation.escalate_pending(db)
    db.expire_all()

    # Ahora el SMTP vuelve.
    _configurar(monkeypatch, db, falla=False)
    escalation.escalate_pending(db)
    db.expire_all()

    assert alerta_vieja.escalated_at is not None, "no ha reintentado al volver el correo"
    enviados = db.query(AlertNotification).filter(
        AlertNotification.alert_id == alerta_vieja.id,
        AlertNotification.status == "sent",
    ).count()
    assert enviados == 1, "el aviso no ha llegado nunca"


def test_no_reintenta_para_siempre(db, monkeypatch, alerta_vieja):
    """Con un SMTP mal configurado de raíz, se rinde y lo dice."""
    _configurar(monkeypatch, db, falla=True)

    for _ in range(escalation.INTENTOS_MAXIMOS + 2):
        escalation.escalate_pending(db)
        db.expire_all()

    assert alerta_vieja.escalated_at is not None, "seguiría reintentando eternamente"
    fallidos = db.query(AlertNotification).filter(
        AlertNotification.alert_id == alerta_vieja.id,
        AlertNotification.status == "failed",
    ).count()
    assert fallidos <= escalation.INTENTOS_MAXIMOS + 1, (
        f"{fallidos} filas fallidas: la tabla se llenaría"
    )


def test_cuando_sale_a_la_primera_se_marca_y_no_se_repite(db, monkeypatch, alerta_vieja):
    _configurar(monkeypatch, db, falla=False)

    assert escalation.escalate_pending(db) == 1
    db.expire_all()
    assert alerta_vieja.escalated_at is not None
    assert escalation.escalate_pending(db) == 0, "ha escalado dos veces la misma alerta"
