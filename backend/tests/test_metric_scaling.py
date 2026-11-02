"""Metric scaling, and the vendor OIDs the templates ship.

Why this file exists: the templates shipped OIDs that were checked against
nothing. iDRAC returns tenths of a degree, so a 27.5 °C inlet was stored as
275 °C; APC column 7 is FAHRENHEIT in tenths and was being polled and labelled
°C; the HPE OIDs were missing an index component, so they returned nothing at
all; and the HPE "fan speed" OID pointed at the fan *condition*.

These tests pin the values that were verified against the vendor MIBs
(CPQHLTH-MIB, IDRAC-MIB, PowerNet-MIB), so the same class of mistake cannot
come back silently.
"""
from __future__ import annotations

from app.models import STATUS_OK, Device, MetricCatalog, MetricPoint
from app.services import poller, templates
from app.services.collector import Reading, classify

# --------------------------------------------------------------------------
# Lo que dicen los MIB. Si alguien cambia un OID, que falle aquí y no en el
# rack de un cliente.
# --------------------------------------------------------------------------
ESPERADO = {
    "dell-idrac": {
        # temperatureProbeReading .700.20.1.6, indexado chasis.sonda, DÉCIMAS.
        # Sonda 1 = "System Board Inlet Temp", 3 = CPU 1.
        "temp_inlet": ("1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1", 0.1, "°C"),
        "temp_cpu": ("1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.3", 0.1, "°C"),
        "fan_rpm": ("1.3.6.1.4.1.674.10892.5.4.700.12.1.6.1.1", 1.0, "rpm"),
    },
    "hpe-ilo": {
        # cpqHeTemperatureCelsius .6.8.1.4, indexado chasis.sensor, grados enteros.
        "temp_inlet": ("1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", 1.0, "°C"),
        "temp_cpu": ("1.3.6.1.4.1.232.6.2.6.8.1.4.1.2", 1.0, "°C"),
        # cpqHeFltTolFanCurrentSpeed es la columna 12. La 9 es el ESTADO.
        "fan_rpm": ("1.3.6.1.4.1.232.6.2.6.7.1.12.1.1", 1.0, "rpm"),
    },
    "apc-pdu": {
        # rPDU2SensorTempHumidityStatusTempC: columna 8, DÉCIMAS de grado C.
        # La columna 7 es la misma lectura en FAHRENHEIT.
        "temp_inlet": ("1.3.6.1.4.1.318.1.1.26.10.2.2.1.8.1", 0.1, "°C"),
        # rPDUIdent 15 = voltaje. El 16 son vatios.
        "voltage": ("1.3.6.1.4.1.318.1.1.12.1.15.0", 1.0, "V"),
        # rPDULoadStatusLoad: décimas de amperio.
        "current": ("1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1", 0.1, "A"),
    },
}


def test_template_oids_and_scales_match_the_mibs():
    for plantilla, metricas in ESPERADO.items():
        tpl = templates.get(plantilla)
        assert tpl is not None, plantilla
        por_nombre = {m[0]: m for m in tpl["metrics"]}
        for nombre, (oid, escala, unidad) in metricas.items():
            assert nombre in por_nombre, f"{plantilla} perdió la métrica {nombre}"
            _, _, u, o, s, _ = por_nombre[nombre]
            assert o == oid, f"{plantilla}.{nombre}: OID {o} != {oid}"
            assert s == escala, f"{plantilla}.{nombre}: escala {s} != {escala}"
            assert u == unidad, f"{plantilla}.{nombre}: unidad {u} != {unidad}"


def test_every_template_metric_is_well_formed():
    for nombre, tpl in templates.TEMPLATES.items():
        for m in tpl["metrics"]:
            assert len(m) == 6, f"{nombre}: {m[0]} no tiene los 6 campos"
            _, _, _, oid, escala, intervalo = m
            assert oid and all(p.isdigit() for p in oid.split(".")), f"{nombre}: OID raro {oid}"
            assert escala > 0, f"{nombre}: escala no positiva en {m[0]}"
            assert 5 <= intervalo <= 3600, f"{nombre}: intervalo raro en {m[0]}"


def test_vendor_temperature_oids_carry_two_index_components():
    """Las tablas por chasis necesitan .chasis.sensor, no un solo índice.

    Con un componente de menos el aparato responde "No Such Instance" y la
    métrica no da datos nunca, sin ningún error visible.
    """
    for plantilla, prefijo_tabla in (
        ("dell-idrac", "1.3.6.1.4.1.674.10892.5.4.700.20.1.6."),
        ("hpe-ilo", "1.3.6.1.4.1.232.6.2.6.8.1.4."),
    ):
        for m in templates.get(plantilla)["metrics"]:
            oid = m[3]
            if oid.startswith(prefijo_tabla):
                sufijo = oid[len(prefijo_tabla):]
                assert len(sufijo.split(".")) == 2, f"{plantilla}.{m[0]}: índice {sufijo}"


def test_applying_a_template_stores_the_scale(client, operator_headers, db):
    r = client.post("/api/v1/templates/apply", headers=operator_headers,
                    json={"template": "dell-idrac", "name": "pe-scale", "ip": "10.44.0.1"})
    assert r.status_code == 201
    device_id = r.json()["id"]
    fila = (
        db.query(MetricCatalog)
        .filter(MetricCatalog.device_id == device_id, MetricCatalog.name == "temp_inlet")
        .one()
    )
    assert fila.scale == 0.1


class _ColectorFijo:
    """Devuelve siempre el mismo valor crudo, como haría el aparato."""

    def __init__(self, crudo: float) -> None:
        self.crudo = crudo

    def poll(self, device, metrics):
        return [
            Reading(metric_id=m.id, metric_name=m.name, value=self.crudo, status=STATUS_OK,
                    latency_ms=1)
            for m in metrics
        ]


def test_poller_stores_the_scaled_value(db, monkeypatch):
    """275 del iDRAC tienen que quedar guardados como 27,5 °C."""
    device = Device(name="pe-poll", ip="10.44.0.2", enabled=True)
    db.add(device)
    db.flush()
    metrica = MetricCatalog(device_id=device.id, name="temp_inlet", label="Inlet", unit="°C",
                            oid="1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1", scale=0.1,
                            poll_interval_s=15, enabled=True)
    db.add(metrica)
    db.commit()
    metric_id = metrica.id

    monkeypatch.setattr(poller, "build_collector", lambda *a, **k: _ColectorFijo(275.0))
    poller._poll_once_sync()

    punto = (
        db.query(MetricPoint)
        .filter(MetricPoint.metric_id == metric_id)
        .order_by(MetricPoint.id.desc())
        .first()
    )
    assert punto is not None, "el sondeo no guardó ningún punto"
    assert abs(punto.value - 27.5) < 0.001, f"guardó {punto.value}, esperaba 27.5"
    # Y el color: sin escalar, 275 sería crítico por goleada. Ya escalado, 27,5
    # de entrada cae en aviso (la banda de ASHRAE empieza en 27), no en crítico.
    # Lo importante es que la clasificación se hace sobre el valor ESCALADO.
    assert classify("temp_inlet", 275.0) == STATUS_CRIT
    assert punto.status != STATUS_CRIT


def test_poller_leaves_unscaled_metrics_alone(db, monkeypatch):
    device = Device(name="hp-poll", ip="10.44.0.3", enabled=True)
    db.add(device)
    db.flush()
    metrica = MetricCatalog(device_id=device.id, name="temp_inlet", label="Inlet", unit="°C",
                            oid="1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", scale=1.0,
                            poll_interval_s=15, enabled=True)
    db.add(metrica)
    db.commit()
    metric_id = metrica.id

    monkeypatch.setattr(poller, "build_collector", lambda *a, **k: _ColectorFijo(22.0))
    poller._poll_once_sync()

    punto = (
        db.query(MetricPoint)
        .filter(MetricPoint.metric_id == metric_id)
        .order_by(MetricPoint.id.desc())
        .first()
    )
    assert punto is not None and abs(punto.value - 22.0) < 0.001


def test_scale_missing_in_an_old_row_behaves_as_one(db, monkeypatch):
    """Las filas creadas antes de que existiera la columna la tienen a NULL."""
    device = Device(name="old-poll", ip="10.44.0.4", enabled=True)
    db.add(device)
    db.flush()
    metrica = MetricCatalog(device_id=device.id, name="temp_inlet", label="Inlet", unit="°C",
                            oid="1.2.3.4", scale=1.0, poll_interval_s=15, enabled=True)
    db.add(metrica)
    db.commit()
    metric_id = metrica.id
    # A NULL con SQL a pelo: pasarle None al modelo dispara el default de la
    # columna, y lo que se quiere reproducir aqui es una fila vieja de verdad.
    from sqlalchemy import text as _text
    db.execute(_text("UPDATE metrics_catalog SET scale = NULL WHERE id = :i"), {"i": metric_id})
    db.commit()

    monkeypatch.setattr(poller, "build_collector", lambda *a, **k: _ColectorFijo(21.0))
    poller._poll_once_sync()

    punto = (
        db.query(MetricPoint)
        .filter(MetricPoint.metric_id == metric_id)
        .order_by(MetricPoint.id.desc())
        .first()
    )
    assert punto is not None and abs(punto.value - 21.0) < 0.001


# --------------------------------------------------------------------------
# Reparacion de lo que ya estaba guardado
# --------------------------------------------------------------------------
def _metrica_vieja(db, ip: str, nombre: str, oid: str, scale=None):
    """Crea una fila como las de antes de 1.2.1: con la escala sin fijar.

    Hay que ponerla a NULL con SQL a pelo. Si se le pasa None al modelo,
    SQLAlchemy entiende "no me has dado valor" y aplica el default de la
    columna (1.0), que es justo lo que NO queremos reproducir aquí.
    """
    from sqlalchemy import text as _text

    device = Device(name=f"legacy-{ip}", ip=ip, enabled=True)
    db.add(device)
    db.flush()
    m = MetricCatalog(device_id=device.id, name=nombre, label=nombre, unit="°C",
                      oid=oid, scale=scale if scale is not None else 1.0,
                      poll_interval_s=30, enabled=True)
    db.add(m)
    db.commit()
    mid = m.id
    if scale is None:
        db.execute(_text("UPDATE metrics_catalog SET scale = NULL WHERE id = :i"), {"i": mid})
        db.commit()
    return mid


def test_repair_fixes_a_pre_1_2_1_hpe_catalog(db):
    from app.database import _reparar_oids_de_plantilla

    # El OID viejo de HPE: le falta un componente del indice, no devolvia nada.
    mid = _metrica_vieja(db, "10.45.0.1", "temp_inlet", "1.3.6.1.4.1.232.6.2.6.8.1.4.2")
    _reparar_oids_de_plantilla()
    db.expire_all()
    fila = db.get(MetricCatalog, mid)
    assert fila.oid == "1.3.6.1.4.1.232.6.2.6.8.1.4.1.1"
    assert fila.scale == 1.0


def test_repair_applies_dell_scaling(db):
    from app.database import _reparar_oids_de_plantilla

    mid = _metrica_vieja(db, "10.45.0.2", "temp_inlet",
                         "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.2")
    _reparar_oids_de_plantilla()
    db.expire_all()
    fila = db.get(MetricCatalog, mid)
    # La sonda 1 es la de entrada, y iDRAC da decimas.
    assert fila.oid == "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.1"
    assert fila.scale == 0.1


def test_repair_moves_apc_off_the_fahrenheit_neighbour(db):
    from app.database import _reparar_oids_de_plantilla

    mid = _metrica_vieja(db, "10.45.0.3", "temp_inlet", "1.3.6.1.4.1.318.1.1.26.6.3.1.7.1")
    _reparar_oids_de_plantilla()
    db.expire_all()
    fila = db.get(MetricCatalog, mid)
    assert fila.oid == "1.3.6.1.4.1.318.1.1.26.10.2.2.1.8.1"
    assert fila.scale == 0.1


def test_repair_does_not_touch_a_metric_the_operator_configured(db):
    from app.database import _reparar_oids_de_plantilla

    # Escala ya fijada = fila posterior al cambio, o tocada a mano. No se toca.
    mid = _metrica_vieja(db, "10.45.0.4", "temp_inlet",
                         "1.3.6.1.4.1.232.6.2.6.8.1.4.2", scale=2.0)
    _reparar_oids_de_plantilla()
    db.expire_all()
    fila = db.get(MetricCatalog, mid)
    assert fila.oid == "1.3.6.1.4.1.232.6.2.6.8.1.4.2"
    assert fila.scale == 2.0


def test_repair_is_idempotent(db):
    from app.database import _reparar_oids_de_plantilla

    mid = _metrica_vieja(db, "10.45.0.5", "fan_rpm", "1.3.6.1.4.1.232.6.2.6.7.1.9.1")
    _reparar_oids_de_plantilla()
    _reparar_oids_de_plantilla()
    db.expire_all()
    fila = db.get(MetricCatalog, mid)
    assert fila.oid == "1.3.6.1.4.1.232.6.2.6.7.1.12.1.1"
    assert fila.scale == 1.0


# --------------------------------------------------------------------------
# La entrada y un componente no se miden con la misma vara
# --------------------------------------------------------------------------
# Esto lo encontro la auditoria: las bandas de color eran 70/80 para CUALQUIER
# metrica que empezara por "temp", asi que una ENTRADA a 45 grados salia verde.
# Toda nuestra documentacion dice lo contrario: 27 nominal, 27-32 aviso, 32+
# critico para el aire que entra.
from app.models import STATUS_CRIT, STATUS_WARN  # noqa: E402


def test_intake_uses_ashrae_bands_not_cpu_bands():
    assert classify("temp_inlet", 24.0) == STATUS_OK
    assert classify("temp_inlet", 29.0) == STATUS_WARN
    assert classify("temp_inlet", 33.0) == STATUS_CRIT
    # El caso que antes salia verde y no deberia.
    assert classify("temp_inlet", 45.0) == STATUS_CRIT


def test_component_temperature_keeps_its_own_bands():
    # Una CPU a 60 grados bajo carga es normal y no puede pintarse en rojo.
    assert classify("temp_cpu", 60.0) == STATUS_OK
    assert classify("temp_cpu", 72.0) == STATUS_WARN
    assert classify("temp_cpu", 85.0) == STATUS_CRIT


def test_all_intake_aliases_share_the_same_bands():
    from app.services.collector import METRICAS_DE_ENTRADA

    for nombre in METRICAS_DE_ENTRADA:
        assert classify(nombre, 33.0) == STATUS_CRIT, nombre
        assert classify(nombre, 24.0) == STATUS_OK, nombre


# --------------------------------------------------------------------------
# La temperatura que representa a un equipo es la de ENTRADA
# --------------------------------------------------------------------------
def _poner_en_cache(device_id, pares, db=None):
    """Mete valores en la caché Y crea su métrica en el catálogo.

    compute_status ignora lo que no esté en el catálogo —para que borrar una
    métrica la quite del estado del equipo—, así que el atajo de escribir en la
    caché sin su fila montaba un estado que no puede existir en producción.
    """
    from datetime import datetime, timezone

    from app.models import MetricCatalog
    from app.services.poller import latest

    ahora = datetime.now(timezone.utc)
    for nombre, valor in pares:
        if db is not None:
            existe = (
                db.query(MetricCatalog)
                .filter(MetricCatalog.device_id == device_id, MetricCatalog.name == nombre)
                .first()
            )
            if existe is None:
                db.add(MetricCatalog(device_id=device_id, name=nombre, label=nombre,
                                     unit="°C", oid="1.1", scale=1.0, poll_interval_s=30))
                db.commit()
        latest.update(device_id, nombre, valor, classify(nombre, valor), ahora, "°C")


def test_device_temperature_prefers_the_intake_over_the_cpu(db):
    from app.routers.devices import compute_status

    d = Device(name="pe-intake", ip="10.46.0.1", enabled=True)
    db.add(d); db.commit()
    _poner_en_cache(d.id, [("temp_cpu", 68.0), ("temp_inlet", 23.0)], db)
    s = compute_status(d)
    # 68 es la CPU y es normal; 23 es la sala. La tarjeta tiene que decir 23.
    assert s.temperature == 23.0


def test_a_device_with_only_an_intake_sensor_still_shows_a_temperature(db):
    from app.routers.devices import compute_status

    # Un PDU de APC no tiene temp_cpu: antes salia SIN temperatura ninguna.
    d = Device(name="apc-only-inlet", ip="10.46.0.2", enabled=True)
    db.add(d); db.commit()
    _poner_en_cache(d.id, [("temp_inlet", 24.5), ("voltage", 230.0)], db)
    s = compute_status(d)
    assert s.temperature == 24.5


def test_a_device_with_only_a_cpu_sensor_falls_back_to_it(db):
    from app.routers.devices import compute_status

    d = Device(name="solo-cpu", ip="10.46.0.3", enabled=True)
    db.add(d); db.commit()
    _poner_en_cache(d.id, [("temp_cpu", 55.0)], db)
    s = compute_status(d)
    assert s.temperature == 55.0


def test_repair_leaves_a_note_on_the_device_timeline(db):
    """Sin la nota, el escalon en la grafica no tiene explicacion.

    El historico anterior y el nuevo conviven en la misma serie: quien mire la
    grafica ve un valor que cae de 275 a 27,5 sin motivo, y una regla de alerta
    ajustada a mano sobre los numeros viejos deja de dispararse en silencio.
    """
    from app.database import _reparar_oids_de_plantilla
    from app.models import Annotation

    mid = _metrica_vieja(db, "10.47.0.1", "temp_inlet",
                         "1.3.6.1.4.1.674.10892.5.4.700.20.1.6.1.2")
    fila = db.get(MetricCatalog, mid)
    device_id = fila.device_id

    _reparar_oids_de_plantilla()
    db.expire_all()

    notas = db.query(Annotation).filter(Annotation.device_id == device_id).all()
    assert len(notas) == 1, "no ha quedado constancia del cambio"
    n = notas[0]
    assert n.metric == "temp_inlet"
    assert "revísala" in n.text or "revisala" in n.text
    assert "x0.1" in n.text


def test_repair_notes_are_not_duplicated_on_every_boot(db):
    from app.database import _reparar_oids_de_plantilla
    from app.models import Annotation

    mid = _metrica_vieja(db, "10.47.0.2", "fan_rpm", "1.3.6.1.4.1.232.6.2.6.7.1.9.1")
    device_id = db.get(MetricCatalog, mid).device_id
    _reparar_oids_de_plantilla()
    _reparar_oids_de_plantilla()
    _reparar_oids_de_plantilla()
    db.expire_all()
    notas = db.query(Annotation).filter(Annotation.device_id == device_id).all()
    assert len(notas) == 1, f"ha dejado {len(notas)} notas en vez de una"
