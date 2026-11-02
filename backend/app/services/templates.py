"""Per-vendor device templates (Fase 2).

A template is a named set of metric definitions so a new device of a known
model starts with the right catalog in one step. Alert thresholds live on rules
(scoped by tag/device), so templates only carry the metrics to poll.

Each metric tuple is (name, label, unit, oid, scale, poll_interval_s).

``scale`` multiplies the raw SNMP value to get the unit named in ``unit``. It is
not decoration: iDRAC returns 275 for 27.5 °C and APC returns tenths of an amp,
so a template without it shows a cool server room as 275 °C and never fires a
threshold set at 35.

Every OID below was checked against the vendor MIB (CPQHLTH-MIB, IDRAC-MIB,
PowerNet-MIB), including the number of index components: most of these tables
are indexed by *chassis* and *sensor*, so an instance ends in ``.1.1`` and an
OID ending in a single ``.1`` returns "No Such Instance" and no data at all.

Index numbers are the usual layout for each vendor, not a guarantee. They are a
starting catalog the operator can correct per device; the vendor guides at
rackmon.app explain how to confirm which sensor is which.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "generic-server": {
        "vendor": "Generic",
        # ENTITY-SENSOR-MIB (entPhySensorValue) plus the usual net-snmp host
        # counters. Deliberately a best-effort starting point: entPhysicalIndex
        # numbering is specific to each box, and strictly the value should be
        # read together with entPhySensorScale/Precision. Use a vendor template
        # when there is one.
        "metrics": [
            ("temp_cpu", "CPU temperature", "°C", "1.3.6.1.2.1.99.1.1.1.4.1", 1.0, 15),
            ("temp_inlet", "Inlet temperature", "°C", "1.3.6.1.2.1.99.1.1.1.4.2", 1.0, 15),
            ("cpu_load", "CPU load", "%", "1.3.6.1.4.1.2021.10.1.3.1", 1.0, 30),
            ("mem_used", "Memory used", "%", "1.3.6.1.4.1.2021.4.6.0", 1.0, 30),
            ("fan_rpm", "Fan speed", "rpm", "1.3.6.1.2.1.99.1.1.1.4.3", 1.0, 30),
        ],
    },
    "dell-idrac": {
        "vendor": "Dell",
        # IDRAC-MIB. temperatureProbeReading is .700.20.1.6, indexed
        # chassis.probe, and reports TENTHS of a degree -> scale 0.1.
        # Probe 1 is "System Board Inlet Temp", 2 is exhaust, 3 is CPU 1.
        # coolingDeviceReading (.700.12.1.6) is already in RPM.
        "metrics": [
            ("temp_inlet", "Inlet temperature", "°C",
             "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1", 0.1, 15),
            ("temp_cpu", "CPU temperature", "°C",
             "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.3", 0.1, 15),
            ("fan_rpm", "Fan speed", "rpm",
             "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1", 1.0, 30),
        ],
    },
    "hpe-ilo": {
        "vendor": "HPE",
        # CPQHLTH-MIB. cpqHeTemperatureCelsius is .6.8.1.4, indexed
        # chassis.sensor, in whole degrees -> no scaling.
        # Sensor 1 is the ambient/intake probe ("01-Inlet Ambient" on Gen8+),
        # sensor 2 is CPU 1. Confirm with cpqHeTemperatureLocale (.6.8.1.3):
        # the ambient sensor is the one whose locale is 11.
        # Fan RPM is cpqHeFltTolFanCurrentSpeed (.6.7.1.12) — column 9 is the
        # fan *condition*, not its speed.
        "metrics": [
            ("temp_inlet", "Inlet temperature", "°C",
             "1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", 1.0, 15),
            ("temp_cpu", "CPU temperature", "°C",
             "1.3.6.1.4.1.232.6.2.6.8.1.4.1.2", 1.0, 15),
            ("fan_rpm", "Fan speed", "rpm",
             "1.3.6.1.4.1.232.6.2.6.7.1.12.1.1", 1.0, 30),
        ],
    },
    "apc-pdu": {
        "vendor": "APC",
        # PowerNet-MIB, rPDU2 tree (rPDU2 = hardware 26, rPDU2Sensor = rPDU2 10).
        # rPDU2SensorTempHumidityStatusTempC is column 8 and reports TENTHS of a
        # degree Celsius -> scale 0.1. Column 7 is the same reading in
        # FAHRENHEIT, which is a quietly catastrophic thing to poll and label °C.
        # rPDULoadStatusLoad is in tenths of an amp. rPDUIdent 15 is the line
        # voltage; 16 is power in watts, not volts.
        "metrics": [
            ("temp_inlet", "Ambient temperature", "°C",
             "1.3.6.1.4.1.318.1.1.26.10.2.2.1.8.1", 0.1, 30),
            ("voltage", "Input voltage", "V",
             "1.3.6.1.4.1.318.1.1.12.1.15.0", 1.0, 30),
            ("current", "Load current", "A",
             "1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1", 0.1, 30),
        ],
    },
}


# ---------------------------------------------------------------------------
# Catálogo de arranque para un equipo creado sin métricas
# ---------------------------------------------------------------------------
# Hasta la 1.2.3 esto eran OID de CISCO para TODO el mundo, y no solo al crear un
# equipo a mano: también al importar desde el descubrimiento de red, que es la vía
# masiva. Alguien escaneaba su subred, importaba cuarenta equipos de cinco marcas
# y los cuarenta se llevaban el catálogo de un switch Cisco. En cualquier cosa que
# no fuera Cisco eso devuelve "no hay datos" sin un solo error visible: el equipo
# aparece creado, enchufado y mudo, y no hay nada en pantalla que explique por qué.
#
# Ahora: si sabemos el fabricante y tenemos una plantilla comprobada contra su
# MIB, se usa esa. Si no, se usa la neutral (ENTITY-SENSOR-MIB, RFC 3433), que al
# menos es el estándar que cualquier fabricante puede implementar, en vez de la
# rama privada de una empresa concreta.
# Señales FUERTES: nombran el producto, no solo a la empresa. Si aparece una de
# estas, se sabe qué hay al otro lado.
_SENALES_FUERTES = (
    ("idrac", "dell-idrac"),
    ("poweredge", "dell-idrac"),
    ("ilo", "hpe-ilo"),
    ("proliant", "hpe-ilo"),
    ("rpdu", "apc-pdu"),
    ("netbotz", "apc-pdu"),
    ("smart-ups", "apc-pdu"),
)

# Señales DÉBILES: solo dicen la empresa. Dell fabrica servidores, switches y
# monitores; Hewlett-Packard fabrica desde servidores hasta impresoras de
# sobremesa. Valen únicamente si no hay nada que las desmienta.
_SENALES_DEBILES = (
    ("dell", "dell-idrac"),
    ("hewlett", "hpe-ilo"),
    ("hpe", "hpe-ilo"),
    ("apc", "apc-pdu"),
    ("schneider", "apc-pdu"),
)

# Lo que desmiente a una señal débil: productos de esas mismas marcas que NO son
# un servidor con iDRAC/iLO ni una PDU de rack. Un "Hewlett-Packard HP LaserJet
# 4200" contiene "hewlett", y con la regla anterior se llevaba el catálogo de
# iLO: el SNMP respondía "No Such Instance" y la impresora quedaba creada,
# habilitada y muda, sin un error en pantalla. Que es justo lo que este cambio
# venía a evitar.
_DESMIENTEN = (
    "laserjet", "officejet", "deskjet", "designjet", "printer", "impresora",
    "procurve", "aruba", "msa", "storeonce", "storageworks",
    "powerconnect", "force10", "networking", "switch", "nexus", "catalyst",
)


def plantilla_para(vendor: str | None) -> str:
    """Qué plantilla le toca a un fabricante. Ante la duda, la neutral.

    Se mira el texto entero del fabricante (que en el descubrimiento sale del
    sysDescr, y ahí cabe el modelo). Primero las señales fuertes, que nombran el
    producto. Después las débiles, que solo nombran la empresa, y solo si nada en
    el texto las desmiente.

    Equivocarse aquí no da un error: da un equipo creado, habilitado y mudo. Por
    eso, ante la duda, el estándar abierto antes que la rama privada de nadie.
    """
    v = (vendor or "").strip().lower()
    if not v:
        return "generic-server"

    for aguja, plantilla in _SENALES_FUERTES:
        if aguja in v:
            return plantilla

    if any(d in v for d in _DESMIENTEN):
        return "generic-server"

    for aguja, plantilla in _SENALES_DEBILES:
        if aguja in v:
            return plantilla

    return "generic-server"


def catalogo_por_defecto(vendor: str | None) -> list[tuple]:
    """Las métricas con las que arranca un equipo creado sin especificarlas.

    Devuelve tuplas de 6: (nombre, etiqueta, unidad, oid, escala, intervalo).
    """
    return list(TEMPLATES[plantilla_para(vendor)]["metrics"])


# ---------------------------------------------------------------------------
# Reparación de los catálogos que ya existen
# ---------------------------------------------------------------------------
# Los dispositivos creados con una plantilla anterior a la 1.2.1 se quedaron con
# los OID malos guardados en su catálogo: arreglar la plantilla no les sirve de
# nada. Esto los corrige al arrancar.
#
# Cada entrada es (nombre de métrica, OID antiguo) -> (OID bueno, escala). Solo
# se aplica a filas cuya escala sigue sin fijar, que es exactamente lo que
# distingue a una fila creada antes de este cambio: así no se toca nada que el
# operador haya ajustado a mano, y repetirlo no hace nada.
LEGACY_OID_FIXES: dict[tuple[str, str], tuple[str, float]] = {
    # Dell: décimas de grado sin aplicar, y la sonda 1 es la de entrada, no la CPU.
    ("temp_cpu", "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1"):
        ("1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.3", 0.1),
    ("temp_inlet", "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.2"):
        ("1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1", 0.1),
    ("fan_rpm", "1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1"):
        ("1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1", 1.0),
    # HPE: faltaba un componente del índice, así que no devolvían nada.
    ("temp_cpu", "1.3.6.1.4.1.232.6.2.6.8.1.4.1"):
        ("1.3.6.1.4.1.232.6.2.6.8.1.4.1.2", 1.0),
    ("temp_inlet", "1.3.6.1.4.1.232.6.2.6.8.1.4.2"):
        ("1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", 1.0),
    ("fan_rpm", "1.3.6.1.4.1.232.6.2.6.7.1.9.1"):
        ("1.3.6.1.4.1.232.6.2.6.7.1.12.1.1", 1.0),
    # APC: árbol equivocado en la temperatura, vatios donde decía voltios, y
    # décimas de amperio en la corriente (ese OID ya era el bueno).
    ("temp_inlet", "1.3.6.1.4.1.318.1.1.26.6.3.1.7.1"):
        ("1.3.6.1.4.1.318.1.1.26.10.2.2.1.8.1", 0.1),
    ("voltage", "1.3.6.1.4.1.318.1.1.12.1.16.0"):
        ("1.3.6.1.4.1.318.1.1.12.1.15.0", 1.0),
    ("current", "1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1"):
        ("1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1", 0.1),
}


def list_templates() -> list[dict]:
    return [
        {
            "name": name,
            "vendor": tpl["vendor"],
            "metrics": [{"name": m[0], "label": m[1], "unit": m[2]} for m in tpl["metrics"]],
        }
        for name, tpl in TEMPLATES.items()
    ]


def get(name: str) -> dict | None:
    return TEMPLATES.get(name)
