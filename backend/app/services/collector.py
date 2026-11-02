"""Metric collection.

The poller talks to devices through a small ``Collector`` interface. Two
implementations exist:

* ``SimulatedCollector`` — generates realistic, time-varying readings with no
  hardware. It is the default so the whole platform runs and is testable on any
  machine, and it powers the automated tests and the demo.
* ``SnmpCollector`` — performs real SNMP GETs via pysnmp. It is wired in and
  selected with ``RACKMON_POLLER_USE_SIMULATOR=false``; the simulator remains
  the guaranteed-working path.

Both return the same normalized ``Reading`` objects, so nothing downstream
(storage, real-time fan-out, alerting) cares which one is in use — the SNMP
dependency is isolated behind this interface (mitigation for vendor lock-in in
the project spec, §20).
"""
from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import dataclass

from ..models import (
    STATUS_CRIT,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_WARN,
    Device,
    MetricCatalog,
)


@dataclass
class Reading:
    metric_id: int
    metric_name: str
    value: float
    status: int
    latency_ms: int


# El "latido" de un equipo: no sale de ningún OID, lo fabrica el sondeador en
# cada barrido y vale 1 si el equipo contestó algo aprovechable y 0 si no.
#
# Existe porque hasta ahora un equipo que dejaba de contestar del todo no
# generaba NADA: el sondeador registraba un aviso en el log, sumaba uno a un
# contador de Prometheus y pasaba al siguiente. El motor de alertas solo mira
# lecturas, y de un equipo mudo no llega ninguna, así que no había alerta, ni
# correo, ni Slack. La única señal era la tarjeta puesta en gris para quien
# estuviera mirando la pantalla en ese momento. Un rack entero podía quedarse
# sin vigilancia un fin de semana sin que nadie se enterara, que es justo lo
# contrario de para lo que se instala esto.
#
# Al convertirlo en una métrica más, toda la maquinaria que ya existe —reglas,
# ventana de persistencia, deduplicación, silencio en mantenimiento,
# notificaciones, resolución automática y el informe de disponibilidad— sirve
# sin tocar nada: la regla de arranque "Device unreachable" es `< 1`.
METRICA_ALCANZABLE = "device_reachable"


# Métricas que miden el AIRE QUE ENTRA, no un componente. Se llaman así en las
# plantillas de fabricante y en el catálogo por defecto.
METRICAS_DE_ENTRADA = ("temp_inlet", "temp_ambient", "temp_intake", "temp_room")


def es_de_entrada(metric_name: str) -> bool:
    """¿Esta métrica mide el aire que entra?

    Compara por FAMILIA, no por igualdad. Un equipo con dos sondas de aire las
    llama "temp_inlet" y "temp_inlet_2", y el segundo nombre no estaba en la
    lista: se juzgaba con la escala de un componente, así que un pasillo a 41 °C
    —nueve grados por encima del crítico que publicamos en nuestras propias
    guías— salía en verde, sin alerta y fuera del ranking de más calientes. Es
    exactamente el fallo que este producto existe para evitar.

    Se exige que el sufijo empiece por "_" o por un dígito para no tragarse un
    "temp_inletfoo" inventado, pero sí "temp_inlet_2", "temp_inlet2" y
    "temp_ambient_rear".
    """
    n = (metric_name or "").strip().lower()
    for base in METRICAS_DE_ENTRADA:
        if n == base:
            return True
        if n.startswith(base):
            resto = n[len(base):]
            if resto and (resto[0] == "_" or resto[0].isdigit()):
                return True
    return False

# Dos escalas distintas, porque son dos cosas distintas. Una CPU a 70 °C bajo
# carga es normal; una ENTRADA a 70 °C no existe: si la ves, o el sensor está
# roto o la sala está ardiendo. Los cortes de la entrada son los mismos que
# publicamos en las guías (hasta 27 nominal, 27-32 aviso, 32+ crítico), que a su
# vez salen del rango recomendado por ASHRAE.
_BANDAS_ENTRADA = (32.0, 27.0)     # (crítico, aviso)
_BANDAS_COMPONENTE = (80.0, 70.0)


# Números que los fabricantes devuelven cuando un sensor NO se puede leer.
#
# No son temperaturas: son "no lo sé" disfrazado de número. El MIB de HPE
# (CPQHLTH) documenta -1 como "no disponible" para cpqHeTemperatureCelsius, y
# otros usan -99, -999 o el máximo del entero con signo.
#
# Esto importa más que ningún otro valor raro: una sonda muerta que devuelve -1
# se clasificaba como NORMAL —está por debajo de 27— y se guardaba como una
# lectura de -1 °C. O sea que el sensor averiado salía en el panel como lo más
# frío del rack, en cian, sin alerta, tirando hacia abajo la media de la sala y
# cayendo al final del ranking de más calientes. Un producto que existe para
# avisar de que algo se calienta estaba diciendo "todo en orden" justo cuando se
# había quedado ciego.
_CENTINELAS = (-1.0, -99.0, -999.0, -32768.0, 32767.0, 65535.0)

# Ventana física de una lectura creíble, DESPUÉS de aplicar la escala. Una sala
# puede estar a 5 °C con free cooling en enero, y un componente a 110 °C antes de
# apagarse; fuera de esto no hay sensor, hay un error.
TEMP_MIN_CREIBLE = -10.0
TEMP_MAX_CREIBLE = 150.0


def es_centinela(value: float) -> bool:
    """¿Es este el número que un fabricante usa para decir «no puedo leerlo»?

    Se comprueba sobre el valor CRUDO, antes de escalar: iDRAC devuelve décimas,
    así que su -1 se convertiría en -0,1 y pasaría cualquier control de rango.
    """
    try:
        return any(abs(float(value) - c) < 1e-9 for c in _CENTINELAS)
    except (TypeError, ValueError):
        return True


def temperatura_creible(value: float) -> bool:
    """¿Cabe esta temperatura en el mundo físico? Se comprueba YA ESCALADA."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    import math as _math

    return _math.isfinite(v) and TEMP_MIN_CREIBLE <= v <= TEMP_MAX_CREIBLE


def classify(metric_name: str, value: float) -> int:
    """Coarse per-reading status used for colouring (rules do the real work)."""
    if metric_name.startswith("temp"):
        crit, warn = (
            _BANDAS_ENTRADA if es_de_entrada(metric_name) else _BANDAS_COMPONENTE
        )
        if value >= crit:
            return STATUS_CRIT
        if value >= warn:
            return STATUS_WARN
    if metric_name == "cpu_load" and value >= 90:
        return STATUS_WARN
    if metric_name == "fan_rpm" and value <= 500:
        return STATUS_CRIT
    return STATUS_OK


class SimulatedCollector:
    """Deterministic-per-device pseudo-random telemetry.

    Each device gets a stable random seed derived from its id, so its baseline
    temperature is consistent across restarts, while a diurnal cycle plus noise
    keeps the live charts moving. A device tagged ``hot`` runs deliberately warm
    so that alert rules fire, which makes the end-to-end demo observable.
    """

    def _seed(self, device_id: int, salt: str = "") -> float:
        h = hashlib.sha256(f"{device_id}:{salt}".encode()).hexdigest()
        return int(h[:8], 16) / 0xFFFFFFFF  # 0..1

    def _baseline(self, device: Device, metric: MetricCatalog) -> float:
        base_frac = self._seed(device.id, metric.name)
        if metric.name.startswith("temp"):
            # Inlet cooler than CPU; baseline 22-35 C, hotter devices higher.
            floor = 20.0 if "inlet" in metric.name else 30.0
            span = 8.0 if "inlet" in metric.name else 12.0
            base = floor + base_frac * span
            # Warmth is a device-side (CPU) effect; the cold-aisle inlet air
            # stays cool regardless, so inlet readings remain realistic.
            if "inlet" not in metric.name:
                tags = device.tags or []
                if "hot" in tags:
                    base += 34.0  # pushes CPU temp toward/over 80 C
                elif "warm" in tags:
                    base += 18.0  # runs noticeably warm (amber)
            return base
        if metric.name == "cpu_load":
            return 25.0 + base_frac * 40.0
        if metric.name == "mem_used":
            return 40.0 + base_frac * 45.0
        if metric.name == "fan_rpm":
            return 3200.0 + base_frac * 2000.0
        return base_frac * 100.0

    def poll(self, device: Device, metrics: list[MetricCatalog]) -> list[Reading]:
        readings: list[Reading] = []
        now = time.time()
        # Simulated network latency for the whole device query.
        latency_ms = int(3 + self._seed(device.id, "lat") * 25)

        # Rare simulated timeout so "unreachable" handling is exercised.
        if random.random() < 0.002 and "hot" not in (device.tags or []):
            for m in metrics:
                readings.append(
                    Reading(m.id, m.name, float("nan"), STATUS_MISSING, latency_ms)
                )
            return readings

        for m in metrics:
            base = self._baseline(device, m)
            # Diurnal component (period ~ 6 min in sim-time for visible motion).
            phase = self._seed(device.id, m.name + "phase") * math.tau
            diurnal = math.sin(now / 60.0 + phase)
            if m.name.startswith("temp"):
                value = base + diurnal * 2.5 + random.uniform(-0.6, 0.6)
                # Occasional transient spike.
                if random.random() < 0.01:
                    value += random.uniform(2, 6)
            elif m.name == "cpu_load":
                value = max(0.0, min(100.0, base + diurnal * 12 + random.uniform(-4, 4)))
            elif m.name == "mem_used":
                value = max(0.0, min(100.0, base + diurnal * 3 + random.uniform(-1, 1)))
            elif m.name == "fan_rpm":
                value = max(0.0, base + diurnal * 250 + random.uniform(-80, 80))
            else:
                value = base + random.uniform(-1, 1)
            value = round(value, 2)
            readings.append(Reading(m.id, m.name, value, classify(m.name, value), latency_ms))
        return readings


class SnmpCollector:
    """Real SNMP collector (pysnmp). Selected via config; simulator is default.

    Kept intentionally small: one GET per configured OID with timeout/retries.
    A production build would batch with GETBULK per device (spec §9); the
    interface and storage path are identical, so that is a drop-in change.
    """

    def __init__(self, timeout: float = 2.0, retries: int = 2) -> None:
        self.timeout = timeout
        self.retries = retries

    def poll(self, device: Device, metrics: list[MetricCatalog]) -> list[Reading]:
        import asyncio

        try:
            return asyncio.run(self._poll_async(device, metrics))
        except RuntimeError:
            # An event loop is already running (rare in the sync poller path):
            # run the coroutine on a fresh loop instead.
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._poll_async(device, metrics))
            finally:
                loop.close()

    def _build_auth(self, device: Device):
        """Return the pysnmp auth object for this device.

        SNMPv3 devices use a USM user built from their stored (encrypted)
        credentials — auth+priv (authPriv), auth-only, or neither — which is a
        hard requirement for enterprise/government sites that forbid the
        plaintext community strings of v1/v2c. Everything else uses a community.
        """
        if device.snmp_version == "3":
            from . import snmpv3

            cfg = snmpv3.decode(device.snmpv3_enc)
            if not cfg:
                raise RuntimeError(
                    f"device {device.id} is configured for SNMPv3 but has no stored credentials"
                )
            return snmpv3.build_usm(cfg)

        from pysnmp.hlapi.asyncio import CommunityData

        from ..crypto import decrypt

        community = decrypt(device.snmp_community_enc) or "public"
        return CommunityData(community, mpModel=0 if device.snmp_version == "1" else 1)

    async def _poll_async(self, device: Device, metrics: list[MetricCatalog]) -> list[Reading]:
        try:
            from pysnmp.hlapi.asyncio import (
                ContextData,
                ObjectIdentity,
                ObjectType,
                SnmpEngine,
                UdpTransportTarget,
                getCmd,
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "pysnmp is required for real SNMP polling; install it or set "
                "RACKMON_POLLER_USE_SIMULATOR=true"
            ) from exc

        auth = self._build_auth(device)
        engine = SnmpEngine()
        target = UdpTransportTarget(
            (device.ip, device.snmp_port), timeout=self.timeout, retries=self.retries
        )

        readings: list[Reading] = []
        for m in metrics:
            if not m.oid:
                continue
            start = time.time()
            status = STATUS_MISSING
            value = float("nan")
            try:
                err_ind, err_stat, _, var_binds = await getCmd(
                    engine, auth, target, ContextData(), ObjectType(ObjectIdentity(m.oid))
                )
                if not err_ind and not err_stat and var_binds:
                    crudo = float(var_binds[0][1])
                    # El equipo ha respondido, pero responder no es lo mismo que
                    # saber: -1 en CPQHLTH-MIB significa "no disponible". Si se
                    # toma por bueno, una sonda muerta sale en el panel como la
                    # cosa más fría del rack y sin una sola alerta.
                    if es_centinela(crudo):
                        status = STATUS_MISSING
                        value = float("nan")
                    else:
                        value = crudo
                        status = classify(m.name, value)
            except Exception:
                status = STATUS_MISSING
            latency_ms = int((time.time() - start) * 1000)
            readings.append(Reading(m.id, m.name, value, status, latency_ms))
        return readings


def build_collector(use_simulator: bool, timeout: float, retries: int):
    if use_simulator:
        return SimulatedCollector()
    return SnmpCollector(timeout=timeout, retries=retries)
