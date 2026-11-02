"""Un equipo estropeado no puede mandarte mil correos.

Una trampa SNMP no la pedimos nosotros: la manda el equipo cuando quiere, por
UDP, y nada limita cuántas. Un enlace que oscila o un agente que se reinicia en
bucle sueltan cientos por minuto. Hasta ahora cada una creaba una alerta nueva y
disparaba una notificación nueva — sin agrupar, sin silencio entre avisos y sin
tope —, así que un solo equipo averiado podía:

  * llenar la lista de alertas con cientos de entradas idénticas,
  * mandar un correo por cada una y tumbar la cuenta de SMTP por abuso,
  * y dejarlas abiertas para siempre, porque nadie manda luego un «ya pasó».

Lo último es lo más caro: el informe de disponibilidad suma la indisponibilidad
de las alertas críticas abiertas, así que UNA sola trampa crítica dejaba a ese
equipo con un 0 % de disponibilidad en todos los informes futuros.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Alert, AlertNotification, AlertState, Device, utcnow
from app.services import traps


def _equipo(db, ip="10.9.9.9", mantenimiento=False):
    d = Device(name="trampas", ip=ip, enabled=True)
    if mantenimiento:
        d.maintenance_until = utcnow() + timedelta(hours=2)
    db.add(d); db.commit(); db.refresh(d)
    return d


def test_una_racha_de_la_misma_trampa_no_crea_una_alerta_por_paquete(db):
    d = _equipo(db)
    for _ in range(50):
        traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.3", {"if": "eth0"})

    alertas = db.scalars(select(Alert).where(Alert.device_id == d.id)).all()
    assert len(alertas) == 1, (
        f"50 paquetes del mismo equipo y la misma trampa han creado "
        f"{len(alertas)} alertas; la lista de alertas queda inservible"
    )
    assert alertas[0].value == 50.0, "se pierde la cuenta de cuántas veces ha pasado"


def test_una_racha_no_manda_un_aviso_por_paquete(db):
    d = _equipo(db)
    for _ in range(50):
        traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.3")

    avisos = db.scalars(select(AlertNotification)).all()
    assert len(avisos) <= 1, (
        f"se han disparado {len(avisos)} notificaciones por una sola avería; "
        "así se tumba una cuenta de SMTP y se enseña a la gente a filtrar "
        "nuestros correos a la papelera"
    )


def test_trampas_distintas_siguen_avisando_por_separado(db):
    """Que el agrupamiento no se trague avisos de cosas diferentes."""
    d = _equipo(db)
    traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.3")
    traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.4")

    alertas = db.scalars(select(Alert).where(Alert.device_id == d.id)).all()
    assert len(alertas) == 2


def test_un_equipo_en_mantenimiento_no_despierta_a_nadie(db):
    """Se reinicia, suelta una ráfaga, y para eso existe el modo mantenimiento."""
    d = _equipo(db, ip="10.9.9.10", mantenimiento=True)
    a = traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.4")

    assert a is not None, "la trampa debe quedar registrada en el histórico"
    avisos = db.scalars(select(AlertNotification).where(AlertNotification.alert_id == a.id)).all()
    assert avisos == [], (
        "el equipo está en mantenimiento declarado y aun así se ha notificado"
    )


def test_una_trampa_no_se_queda_abierta_para_siempre(db):
    d = _equipo(db)
    a = traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.5", severity="critical")
    # Se envejece a mano para no esperar media hora.
    a.started_at = utcnow() - timedelta(seconds=traps.VIDA_DE_UNA_TRAMPA_S + 60)
    db.commit()

    cerradas = traps.cerrar_trampas_viejas(db)
    db.expire_all()

    assert cerradas == 1
    viva = db.get(Alert, a.id)
    assert viva.state == AlertState.resolved.value, (
        "la alerta de trampa sigue abierta: la lista de activas no se vacía nunca "
        "y el informe de SLA la cuenta como caída permanente"
    )
    assert viva.ended_at is not None, "sin ended_at el informe de SLA la cuenta hasta hoy"


def test_una_trampa_reciente_no_se_cierra_sola(db):
    d = _equipo(db)
    traps.handle_trap(db, d.ip, "1.3.6.1.6.3.1.1.5.6")
    assert traps.cerrar_trampas_viejas(db) == 0
