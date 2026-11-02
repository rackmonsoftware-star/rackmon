"""Background poller.

Periodically wakes, determines which (device, metric) pairs are due based on
their configured poll interval, collects readings, and then:

1. writes them to the time-series store,
2. updates the in-memory "latest value" cache,
3. publishes them to the real-time hub (WebSocket fan-out), and
4. feeds them to the alert engine.

All blocking DB/collector work runs in a worker thread so the event loop stays
responsive. Horizontal scaling (spec §6/§20) shards devices across workers; the
loop body here is exactly what each worker would run.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..config import get_settings
from ..database import session_scope
from ..metrics_prom import DEVICES_GAUGE, POLL_LATENCY, POLLS_TOTAL
from ..models import Device, MetricCatalog, MetricPoint, ensure_aware
from .alert_engine import engine as alert_engine
from .collector import (
    METRICA_ALCANZABLE,
    STATUS_MISSING,
    STATUS_CRIT,
    STATUS_OK,
    Reading,
    build_collector,
    classify,
    es_centinela,
    temperatura_creible,
)
from .realtime import hub

log = logging.getLogger("rackmon.poller")


class LatestCache:
    """Most recent value per (device_id, metric_name) for cheap dashboard reads."""

    def __init__(self) -> None:
        self._data: dict[tuple[int, str], dict] = {}
        self._lock = threading.Lock()

    def update(self, device_id: int, metric: str, value: float, status: int, ts: datetime,
               unit: str = "") -> None:
        with self._lock:
            self._data[(device_id, metric)] = {
                "device_id": device_id, "metric": metric, "value": value,
                "status": status, "unit": unit, "time": ts,
            }

    def get(self, device_id: int, metric: str) -> dict | None:
        with self._lock:
            return self._data.get((device_id, metric))

    def for_device(self, device_id: int) -> list[dict]:
        with self._lock:
            return [v for (d, _), v in self._data.items() if d == device_id]

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._data.values())

    def evict_devices(self, valid_ids: set[int]) -> None:
        with self._lock:
            for key in [k for k in self._data if k[0] not in valid_ids]:
                self._data.pop(key, None)


latest = LatestCache()


def _serialize_alert(alert) -> dict:
    return {
        "type": "alert",
        "id": alert.id,
        "device_id": alert.device_id,
        "metric": alert.metric,
        "severity": alert.severity,
        "state": alert.state,
        "value": alert.value,
        "message": alert.message,
        "started_at": alert.started_at.isoformat() if alert.started_at else None,
    }


def _poll_once_sync() -> tuple[int, list[dict]]:
    """One full sweep (runs in a worker thread).

    Returns the number of points written and a list of serialized alert events
    for alerts whose state changed during this sweep.
    """
    settings = get_settings()
    collector = build_collector(
        settings.poller_use_simulator, settings.snmp_timeout_seconds, settings.snmp_retries
    )
    now_mono = time.monotonic()
    written = 0
    alert_events: list[dict] = []

    with session_scope() as db:
        devices = db.scalars(select(Device).where(Device.enabled.is_(True))).all()
        DEVICES_GAUGE.labels(enabled="true").set(len(devices))

        for device in devices:
            metrics = [m for m in device.metrics if m.enabled and _is_due(device.id, m, now_mono)]
            if not metrics:
                continue

            t0 = time.time()
            readings: list = []
            try:
                readings = collector.poll(device, metrics)
                POLLS_TOTAL.labels(result="ok").inc()
            except Exception as exc:  # pragma: no cover - defensive
                # Antes aquí había un `continue`, y ese `continue` era el agujero:
                # saltaba también la llamada al motor de alertas, así que un equipo
                # que no contesta no generaba absolutamente nada. Ahora seguimos
                # adelante con la lista vacía para poder emitir el latido en 0.
                log.warning("poll failed for device %s: %s", device.id, exc)
                POLLS_TOTAL.labels(result="error").inc()
            POLL_LATENCY.observe(time.time() - t0)

            ts = datetime.now(timezone.utc)
            unit_by_id = {m.id: m.unit for m in metrics}
            scale_by_id = {m.id: (m.scale or 1.0) for m in metrics}
            # ¿Ha CONTESTADO el equipo? Se mira sobre las lecturas tal como
            # llegaron, antes de que el bucle de abajo las filtre. La diferencia
            # importa: una sonda averiada devuelve el centinela del fabricante
            # (-1, -99…) y esa lectura se tira, pero el equipo ha contestado. Si
            # el latido se calculara sobre lo que acaba guardado, un equipo vivo
            # con una sonda rota —y con el resto de métricas en otro intervalo—
            # saldría anunciado como caído. Avisar de una caída que no existe se
            # paga igual de caro que no avisar de la de verdad.
            contesto = any(
                isinstance(r.value, (int, float)) and math.isfinite(r.value) for r in readings
            )
            for r in readings:
                _mark_polled(device.id, r.metric_id, now_mono)
                if not (isinstance(r.value, (int, float)) and math.isfinite(r.value)):
                    continue  # missing/invalid reading: no point stored
                # El centinela se mira sobre el valor CRUDO, antes de escalar.
                # El colector SNMP ya lo filtra, pero esto es la red de debajo: si
                # algún día entra una lectura por otro camino —un plugin, un
                # colector nuevo, una prueba— un -1 seguiría colándose como una
                # temperatura de -1 °C, que es "todo en orden" para classify().
                if es_centinela(r.value):
                    log.warning(
                        "lectura descartada: %s devolvió %s para %s, que es el valor "
                        "que usa el fabricante para decir «no puedo leerlo»",
                        device.name, r.value, r.metric_name,
                    )
                    # NaN, no simplemente saltársela: el motor de alertas recibe
                    # esta misma lista y trata NaN como "no lo sé". Si llegara el
                    # -1 tal cual, la condición "-1 > 32" daría falso, subiría la
                    # racha de limpieza y a los dos ciclos cerraría la alerta viva
                    # mandando un "recuperado" que es mentira.
                    r.value = float("nan")
                    r.status = STATUS_MISSING
                    continue
                escala = scale_by_id.get(r.metric_id) or 1.0
                if escala != 1.0:
                    # Se escala AQUÍ, antes de guardar, de avisar y de clasificar:
                    # iDRAC devuelve 275 para 27,5 °C. Sin esto, el punto guardado,
                    # la alerta y el color de la tarjeta hablarían todos de 275 °C.
                    r.value = r.value * escala
                    r.status = classify(r.metric_name, r.value)
                # Segunda red, DESPUÉS de escalar: el centinela de un fabricante
                # que devuelve décimas (-1 crudo) se queda en -0,1 al escalar y
                # pasaría cualquier control hecho sobre el valor crudo. Una
                # temperatura fuera del mundo físico no se guarda: vale más un
                # hueco honesto en la gráfica que un -0,1 °C que nadie cuestiona.
                if r.metric_name.startswith("temp") and not temperatura_creible(r.value):
                    log.warning(
                        "lectura descartada: %s devolvió %.3f para %s, fuera de lo "
                        "físicamente posible (sensor averiado o no disponible)",
                        device.name, r.value, r.metric_name,
                    )
                    r.value = float("nan")
                    r.status = STATUS_MISSING
                    continue
                db.add(
                    MetricPoint(
                        time=ts, device_id=device.id, metric_id=r.metric_id,
                        value=r.value, status=r.status, latency_ms=r.latency_ms,
                    )
                )
                written += 1
                latest.update(
                    device.id, r.metric_name, r.value, r.status, ts, unit_by_id.get(r.metric_id, "")
                )

            # El latido. No basta con que `poll()` no reviente, porque la vía
            # habitual de un equipo caído no es una excepción: el colector SNMP
            # agota el tiempo OID por OID y devuelve la lista entera en NaN, que
            # es exactamente lo que devuelve también el simulador. Con esto, las
            # dos formas de estar mudo —excepción y silencio— cuentan igual.
            #
            # No se guarda como punto ni entra en la caché del panel: no es una
            # medida del equipo, es nuestra opinión sobre si contesta. Solo viaja
            # al motor de alertas, con metric_id -1 porque no hay fila en el
            # catálogo a la que apuntar (y para entonces el bucle que usa
            # metric_id ya ha terminado).
            readings = list(readings) + [
                Reading(
                    metric_id=-1,
                    metric_name=METRICA_ALCANZABLE,
                    value=1.0 if contesto else 0.0,
                    status=STATUS_OK if contesto else STATUS_CRIT,
                    latency_ms=0,
                )
            ]

            # Alerts evaluated against this batch, same transaction.
            changed = alert_engine.process(db, device, readings)
            for alert in changed:
                alert_events.append(_serialize_alert(alert))

    # Evict cache entries for devices that no longer exist / are disabled, so the
    # in-memory maps don't grow without bound as devices/metrics/rules churn.
    _evict_stale_devices({d.id for d in devices})
    return written, alert_events


# --- due-scheduling (in-memory) -------------------------------------------- #
_last_polled: dict[tuple[int, int], float] = {}


# Ventana que se mira al rehidratar. Suficiente para cubrir cualquier intervalo
# de sondeo razonable y lo bastante corta para que la consulta no barra la tabla.
VENTANA_HIDRATACION_S = 900


def hidratar_desde_bd(ventana_s: int = VENTANA_HIDRATACION_S) -> int:
    """Rellena la caché `latest` con lo último que haya en la base de datos.

    Hace falta porque `latest` vive en memoria del proceso y SOLO la escribe el
    poller. En el despliegue por defecto del chart de Helm el poller va en su
    propio pod (`api.pollerEnabled: false` + un Deployment aparte), así que los
    pods de la API nunca tenían un solo valor: el panel, el mapa térmico, las
    medias y el ranking salían vacíos de forma permanente mientras Postgres se
    llenaba de lecturas. Y lo mismo, en pequeño, cada vez que se reinicia la API.

    Una sola consulta, ordenada por tiempo ascendente para que la última escritura
    de cada métrica sea la que queda.
    """
    from ..models import MetricCatalog as _MC
    from ..models import MetricPoint as _MP

    corte = datetime.now(timezone.utc) - timedelta(seconds=ventana_s)
    puestos = 0
    with session_scope() as db:
        filas = db.execute(
            select(_MP.device_id, _MC.name, _MP.value, _MP.status, _MP.time, _MC.unit)
            .join(_MC, _MC.id == _MP.metric_id)
            .where(_MP.time >= corte)
            .order_by(_MP.time)
        ).all()
        for device_id, nombre, valor, estado, cuando, unidad in filas:
            latest.update(device_id, nombre, valor, estado, ensure_aware(cuando), unidad or "")
            puestos += 1
    if puestos:
        log.info("caché rehidratada desde la base de datos: %s lectura(s)", puestos)
    return puestos


def _is_due(device_id: int, metric: MetricCatalog, now_mono: float) -> bool:
    last = _last_polled.get((device_id, metric.id))
    if last is None:
        return True
    return (now_mono - last) >= max(1, metric.poll_interval_s)


def _mark_polled(device_id: int, metric_id: int, now_mono: float) -> None:
    _last_polled[(device_id, metric_id)] = now_mono


def _evict_stale_devices(valid_ids: set[int]) -> None:
    """Drop in-memory cache entries for devices no longer enabled/present."""
    for key in [k for k in _last_polled if k[0] not in valid_ids]:
        _last_polled.pop(key, None)
    latest.evict_devices(valid_ids)
    alert_engine.evict_devices(valid_ids)


async def _publish_latest_snapshot() -> None:
    """Push the freshest values to subscribed WebSocket clients."""
    for v in latest.all():
        topic = f"device.{v['device_id']}.{v['metric']}"
        await hub.publish(
            topic,
            {
                "type": "metric",
                "device_id": v["device_id"],
                "metric": v["metric"],
                "value": v["value"],
                "status": v["status"],
                "unit": v["unit"],
                "time": v["time"].isoformat(),
            },
        )


async def refrescar_cache(stop: asyncio.Event, cada_s: float = 10.0) -> None:
    """Mantiene la caché al día leyendo de la base de datos.

    Solo se arranca cuando el poller NO corre en este proceso. Es el caso del
    chart de Helm por defecto —un pod de poller aparte y varias réplicas de la
    API— donde la caché en memoria de cada réplica jamás recibiría nada. Sin
    esto, el panel sale vacío para siempre; con un refresco al arranque pero sin
    el periódico, saldría vacío a los noventa segundos, cuando el control de
    frescura marcase todo como "sin datos".
    """
    log.info("refresco de caché activo (cada %ss): el poller no corre en este proceso", cada_s)
    while not stop.is_set():
        try:
            await asyncio.to_thread(hidratar_desde_bd)
        except Exception as exc:  # pragma: no cover - nunca debe tumbar el proceso
            log.warning("no he podido refrescar la caché (%s)", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=cada_s)
        except asyncio.TimeoutError:
            pass


async def run_poller(stop: asyncio.Event) -> None:
    settings = get_settings()
    log.info(
        "poller started (simulator=%s tick=%ss)",
        settings.poller_use_simulator, settings.poller_tick_seconds,
    )
    while not stop.is_set():
        try:
            written, alert_events = await asyncio.to_thread(_poll_once_sync)
            if written:
                await _publish_latest_snapshot()
            for event in alert_events:
                await hub.publish("alerts", event)
                await hub.publish(f"device.{event['device_id']}.alerts", event)
        except Exception as exc:  # pragma: no cover - keep the loop alive
            log.exception("poller tick error: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.poller_tick_seconds)
        except asyncio.TimeoutError:
            pass
    log.info("poller stopped")
