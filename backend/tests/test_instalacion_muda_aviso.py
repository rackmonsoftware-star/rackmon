"""El resumen tiene que delatar una instalación que no puede avisar de nada.

Dos formas de estar muda, las dos vistas en producción: sin reglas de alerta el
motor no dispara nunca, y sin ningún canal configurado un disparo solo deja una
línea en un log. En ambos casos el panel pinta tarjetas rojas y parece que todo
funciona — y la consola, que siempre está, registra «enviado», así que ni el
historial de notificaciones delata el problema.
"""
from __future__ import annotations

from app.models import AlertRule


def _resumen(client, headers):
    r = client.get("/api/v1/overview", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_el_resumen_dice_cuantas_reglas_hay(client, admin_headers, db):
    datos = _resumen(client, admin_headers)
    assert "alert_rules_active" in datos
    assert datos["alert_rules_active"] == db.query(AlertRule).filter(
        AlertRule.enabled.is_(True)
    ).count()


def test_sin_reglas_lo_dice(client, admin_headers, db):
    db.query(AlertRule).delete()
    db.commit()
    assert _resumen(client, admin_headers)["alert_rules_active"] == 0


def test_una_regla_desactivada_no_cuenta(client, admin_headers, db):
    """Desactivarlas todas deja la instalación igual de muda que borrarlas."""
    for r in db.query(AlertRule).all():
        r.enabled = False
    db.commit()
    assert _resumen(client, admin_headers)["alert_rules_active"] == 0


def test_la_consola_no_cuenta_como_canal(client, admin_headers, monkeypatch):
    """La consola siempre está y siempre dice «enviado». Si contara, una
    instalación sin SMTP ni webhooks parecería tener notificaciones."""
    from app.services import notifier

    monkeypatch.setattr(notifier, "_smtp_config", lambda db: {"host": "", "recipients": []})
    monkeypatch.setattr(notifier, "_channels_config", lambda db: {})

    assert _resumen(client, admin_headers)["notification_channels"] == 0


def test_con_smtp_configurado_cuenta_uno(client, admin_headers, monkeypatch):
    from app.services import notifier

    monkeypatch.setattr(notifier, "_smtp_config",
                        lambda db: {"host": "smtp.corp.com", "recipients": ["a@corp.com"]})
    monkeypatch.setattr(notifier, "_channels_config", lambda db: {})

    assert _resumen(client, admin_headers)["notification_channels"] == 1


def test_smtp_sin_destinatarios_no_cuenta(client, admin_headers, monkeypatch):
    """Un servidor SMTP sin a quién escribir no es un canal."""
    from app.services import notifier

    monkeypatch.setattr(notifier, "_smtp_config",
                        lambda db: {"host": "smtp.corp.com", "recipients": []})
    monkeypatch.setattr(notifier, "_channels_config", lambda db: {})

    assert _resumen(client, admin_headers)["notification_channels"] == 0


def test_cuenta_los_webhooks(client, admin_headers, monkeypatch):
    from app.services import notifier

    monkeypatch.setattr(notifier, "_smtp_config", lambda db: {"host": "", "recipients": []})
    monkeypatch.setattr(notifier, "_channels_config", lambda db: {
        "webhook_url": "https://x/1", "slack_webhook_url": "https://x/2",
        "telegram_token": "t", "telegram_chat_id": "1",
    })

    assert _resumen(client, admin_headers)["notification_channels"] == 3


def test_la_demo_publica_no_muestra_el_aviso(client, admin_headers, monkeypatch):
    """En la demo no hay a quién notificar por diseño. El aviso ahí no informa de
    nada: sería lo primero que ve, en ámbar y con pinta de defecto, alguien que
    acaba de pulsar «Ver demo en vivo» desde la web."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", True, raising=False)
    datos = _resumen(client, admin_headers)
    assert datos["demo_mode"] is True


def test_una_instalacion_normal_no_se_marca_como_demo(client, admin_headers, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_mode", False, raising=False)
    assert _resumen(client, admin_headers)["demo_mode"] is False


def test_los_contadores_siguen_diciendo_la_verdad_en_la_demo(client, admin_headers, monkeypatch):
    """Se calla el aviso, no se falsean los números: quien mire el API ve la
    realidad."""
    from app.config import get_settings
    from app.services import notifier

    monkeypatch.setattr(get_settings(), "demo_mode", True, raising=False)
    monkeypatch.setattr(notifier, "_smtp_config", lambda db: {"host": "", "recipients": []})
    monkeypatch.setattr(notifier, "_channels_config", lambda db: {})

    datos = _resumen(client, admin_headers)
    assert datos["notification_channels"] == 0, "el contador debe seguir siendo honesto"
