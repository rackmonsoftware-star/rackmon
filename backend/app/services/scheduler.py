"""Lightweight internal scheduler.

Runs periodic maintenance. Fase-1 implements raw-retention pruning (RF-16). On
TimescaleDB the multi-tier downsampling (1 min / 5 min / 1 h continuous
aggregates with their own retention) is handled by the database itself — see
deploy/timescale/init.sql — so this loop only prunes the raw hypertable. On
SQLite it does the equivalent delete so behaviour matches in development.

Scheduled PDF reports and backups are wired as Phase-2 tasks; the hook points
live here.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from ..config import get_settings
from ..database import session_scope
from ..models import MetricPoint

log = logging.getLogger("rackmon.scheduler")


def prune_raw_points() -> int:
    settings = get_settings()
    dias = settings.raw_retention_days
    # 0 o menos = GUARDAR PARA SIEMPRE, no "borrar todo".
    #
    # Antes, un 0 ponía el corte en «ahora» y la limpieza se llevaba por delante
    # el histórico entero, incluidos los puntos de hace un segundo, cada hora y
    # en silencio. Y 0 es justo lo que escribe quien quiere decir «sin límite»:
    # es la convención en casi todas las herramientas del ramo. Una persona que
    # busca conservarlo todo acababa sin nada, y el único rastro era una línea de
    # log diciendo cuántos millones de puntos había borrado.
    if dias <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=dias)
    with session_scope() as db:
        result = db.execute(delete(MetricPoint).where(MetricPoint.time < cutoff))
        return result.rowcount or 0


def _run_weekly_report() -> bool:
    from .reports import maybe_send_weekly_report

    with session_scope() as db:
        return maybe_send_weekly_report(db)


def _run_escalation() -> int:
    from .escalation import escalate_pending

    with session_scope() as db:
        return escalate_pending(db)


def _cerrar_trampas() -> int:
    from .traps import cerrar_trampas_viejas

    with session_scope() as db:
        return cerrar_trampas_viejas(db)


async def run_scheduler(stop: asyncio.Event) -> None:
    settings = get_settings()
    sweep_interval = max(60, settings.retention_sweep_minutes * 60)
    escalation_interval = 60  # escalation is time-sensitive — check ~every minute
    tick = min(escalation_interval, sweep_interval)
    log.info("scheduler started (retention sweep every %s min, escalation every %ss)",
             settings.retention_sweep_minutes, escalation_interval)
    next_sweep = 0.0
    while not stop.is_set():
        # Time-sensitive: escalate any pending alerts every tick, so escalation
        # meets its ~15-min SLA instead of waiting for the hourly retention sweep.
        try:
            n = await asyncio.to_thread(_run_escalation)
            if n:
                log.info("escalated %s alert(s)", n)
        except Exception as exc:  # pragma: no cover
            log.exception("escalation error: %s", exc)
        # Las trampas SNMP son sucesos, no estados: nadie manda un "ya pasó", así
        # que las cierra el reloj. Si no, la lista de alertas activas no vuelve a
        # vaciarse nunca y el informe de SLA las cuenta como caída permanente.
        try:
            n = await asyncio.to_thread(_cerrar_trampas)
            if n:
                log.info("cerradas %s alerta(s) de trampa por antigüedad", n)
        except Exception as exc:  # pragma: no cover
            log.exception("trap sweep error: %s", exc)
        # Housekeeping: prune raw points + weekly report only every sweep_interval.
        if time.monotonic() >= next_sweep:
            next_sweep = time.monotonic() + sweep_interval
            try:
                removed = await asyncio.to_thread(prune_raw_points)
                if removed:
                    log.info("retention sweep removed %s raw points", removed)
            except Exception as exc:  # pragma: no cover
                log.exception("scheduler error: %s", exc)
            try:
                if await asyncio.to_thread(_run_weekly_report):
                    log.info("weekly report emailed")
            except Exception as exc:  # pragma: no cover
                log.exception("weekly report error: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=tick)
        except asyncio.TimeoutError:
            pass
    log.info("scheduler stopped")
