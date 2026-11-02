"""SNMP trap reception (Fase 2).

Devices can *push* asynchronous notifications (traps) instead of only being
polled. The UDP listener that receives raw traps needs a real network/socket
and is marked no-cover; the trap-handling logic below — resolve the source
device, raise an alert, fan it out through the notifier — is fully unit-tested.
"""
from __future__ import annotations

import asyncio
import logging

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import session_scope
from ..models import Alert, AlertNotification, AlertState, Device, Severity, utcnow

log = logging.getLogger("rackmon.traps")

TRAP_METRIC = "snmp_trap"

# Una trampa no es una medida que se repite cada treinta segundos bajo nuestro
# control: la manda el equipo cuando quiere, y un enlace que oscila o un agente
# que se reinicia en bucle pueden mandar cientos por minuto. Tal como estaba,
# CADA UNA creaba una alerta nueva y disparaba una notificación nueva, sin
# agrupar, sin silencio entre avisos y sin tope. Un solo equipo estropeado podía
# soltar miles de correos en una tarde, tirar la cuenta de SMTP por abuso y
# dejar la lista de alertas inservible — y todo ello lo decide un paquete UDP
# que llega de fuera.
VENTANA_AGRUPACION_S = 300      # la misma trampa del mismo equipo se agrupa
SILENCIO_ENTRE_AVISOS_S = 900   # y no se vuelve a avisar antes de esto

# Y una trampa es un SUCESO, no un estado: nadie manda luego un "ya pasó". Si se
# quedan abiertas para siempre, la lista de alertas activas no vuelve a vaciarse
# nunca y —lo grave— el informe de disponibilidad las cuenta como caída continua:
# una sola trampa crítica dejaba a ese equipo con un 0 % de disponibilidad en
# todos los informes futuros. Se cierran solas pasado este tiempo y se quedan en
# el histórico, que es donde deben estar.
VIDA_DE_UNA_TRAMPA_S = 1800


def handle_trap(db: Session, source_ip: str, trap_oid: str,
                varbinds: dict | None = None,
                severity: str = Severity.warning.value) -> Alert | None:
    """Resolve the source device, record a firing alert, and notify.

    Returns the created Alert, or None if the source IP is unknown.
    """
    from . import notifier

    device = db.scalar(select(Device).where(Device.ip == source_ip))
    if device is None:
        log.warning("trap from unknown source %s ignored", source_ip)
        return None

    ahora = utcnow()
    detail = ", ".join(f"{k}={v}" for k, v in (varbinds or {}).items())
    message = f"SNMP trap {trap_oid}" + (f" ({detail})" if detail else "")
    grupo = f"trap:{trap_oid}"[:64]

    # ¿Hay ya una alerta abierta por esta misma trampa de este mismo equipo?
    repetida = db.scalars(
        select(Alert)
        .where(
            Alert.device_id == device.id,
            Alert.metric == TRAP_METRIC,
            Alert.correlation_id == grupo,
            Alert.state != AlertState.resolved.value,
            Alert.started_at >= ahora - timedelta(seconds=VENTANA_AGRUPACION_S),
        )
        .order_by(Alert.started_at.desc())
    ).first()

    if repetida is not None:
        # `value` lleva la cuenta de repeticiones: es el único campo numérico que
        # tiene una alerta y para una trampa no significaba nada (siempre 0).
        repetida.value = (repetida.value or 1.0) + 1.0
        repetida.message = f"{message} (x{int(repetida.value)} en los últimos minutos)"
        alert = repetida
        db.flush()
    else:
        alert = Alert(
            device_id=device.id, rule_id=None, metric=TRAP_METRIC, severity=severity,
            state=AlertState.firing.value, value=1.0, message=message,
            correlation_id=grupo, started_at=ahora,
        )
        db.add(alert)
        db.flush()

    if device.in_maintenance:
        # Se guarda, no se avisa. Un equipo en mantenimiento se reinicia y suelta
        # una ráfaga de trampas; despertar a alguien con ellas es exactamente lo
        # que el modo mantenimiento existe para evitar. En el camino del sondeo
        # ya se respeta; aquí no se miraba.
        log.info("trap from %s recorded, device in maintenance: no notification", source_ip)
        db.commit()
        return alert

    if _toca_avisar(db, alert, ahora):
        try:
            notifier.dispatch(db, alert, device)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("trap notification failed: %s", exc)
    db.commit()
    log.info("trap from %s -> alert #%s", source_ip, alert.id)
    return alert


def _toca_avisar(db: Session, alert: Alert, ahora) -> bool:
    """¿Ha pasado bastante desde el último aviso de esta alerta?

    Se mira en la base de datos, no en memoria, para que un reinicio del servicio
    no reabra la puerta a la ráfaga de correos que esto evita.
    """
    ultima = db.scalar(
        select(func.max(AlertNotification.sent_at)).where(AlertNotification.alert_id == alert.id)
    )
    if ultima is None:
        return True
    from ..models import ensure_aware

    ultima = ensure_aware(ultima)
    return (ahora - ultima).total_seconds() >= SILENCIO_ENTRE_AVISOS_S


def cerrar_trampas_viejas(db: Session) -> int:
    """Cierra las alertas de trampa que ya han cumplido su vida.

    Nadie manda un "ya pasó" para una trampa, así que sin esto se quedan abiertas
    para siempre: la lista de alertas activas no vuelve a vaciarse y el informe de
    SLA cuenta cada una como indisponibilidad continua hasta el fin de los tiempos.
    """
    corte = utcnow() - timedelta(seconds=VIDA_DE_UNA_TRAMPA_S)
    abiertas = db.scalars(
        select(Alert).where(
            Alert.metric == TRAP_METRIC,
            Alert.state != AlertState.resolved.value,
            Alert.started_at < corte,
        )
    ).all()
    for a in abiertas:
        a.state = AlertState.resolved.value
        a.ended_at = a.ended_at or utcnow()
        a.resolved_at = a.resolved_at or a.ended_at
        if not a.resolve_comment:
            a.resolve_comment = (
                "Auto-resolved: an SNMP trap is a point-in-time event, not a "
                "condition that clears"
            )
    if abiertas:
        db.commit()
        log.info("cerradas %s alerta(s) de trampa por antigüedad", len(abiertas))
    return len(abiertas)


def _on_trap(source_ip: str, trap_oid: str, varbinds: dict) -> None:  # pragma: no cover - callback
    with session_scope() as db:
        handle_trap(db, source_ip, trap_oid, varbinds)


async def run_trap_listener(stop: asyncio.Event) -> None:  # pragma: no cover - needs socket/pysnmp
    """Listen for SNMP traps on the configured UDP port (default 162).

    Requires privileges to bind the port and real devices to send traps, so it
    is opt-in via RACKMON_SNMP_TRAP_ENABLED and not exercised in tests.
    """
    settings = get_settings()
    from pysnmp.carrier.asyncio.dgram import udp
    from pysnmp.entity import config as snmp_config
    from pysnmp.entity import engine
    from pysnmp.entity.rfc3413 import ntfrcv

    snmp_engine = engine.SnmpEngine()
    snmp_config.addTransport(
        snmp_engine, udp.domainName,
        udp.UdpTransport().openServerMode(("0.0.0.0", settings.snmp_trap_port)),
    )
    snmp_config.addV1System(snmp_engine, "rackmon", settings.snmp_trap_community)

    def _cb(engine_, ctx_id, ctx_name, var_binds, cb_ctx):
        try:
            transport = snmp_engine.observer.getExecutionContext(
                "rfc3412.receiveMessage:request")["transportAddress"]
            source_ip = transport[0]
        except Exception:
            source_ip = "0.0.0.0"
        binds = {str(oid): str(val) for oid, val in var_binds}
        trap_oid = next(iter(binds), "unknown")
        _on_trap(source_ip, trap_oid, binds)

    ntfrcv.NotificationReceiver(snmp_engine, _cb)
    log.info("SNMP trap listener started on udp/%s", settings.snmp_trap_port)
    snmp_engine.transportDispatcher.jobStarted(1)
    try:
        while not stop.is_set():
            await asyncio.sleep(0.5)
    finally:
        snmp_engine.transportDispatcher.jobFinished(1)
        snmp_engine.transportDispatcher.closeDispatcher()
        log.info("SNMP trap listener stopped")
