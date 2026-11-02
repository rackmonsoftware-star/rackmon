"""De qué métrica sale la temperatura de un equipo, y qué entra en las medias.

La 1.2.2 separó aire de entrada y componente en las alertas, en el estado y en los
informes de SLA. Faltaban dos sitios:

  - Nadie decía DE QUÉ métrica salía la temperatura, así que la interfaz no podía
    pintarla bien: 32 °C de aire de entrada es crítico y 32 °C de CPU es un equipo
    en reposo, y el color tiene que significar lo mismo que el estado.
  - La pantalla de resumen seguía metiendo en la misma media los 22 °C de aire de
    una PDU y los 70 °C de una CPU, y el ranking de "más calientes" lo encabezaba
    siempre cualquier equipo con sensor de CPU, con la sala fría o ardiendo.
"""
from __future__ import annotations


from datetime import datetime, timezone

from app.models import Device, MetricCatalog
from app.routers.devices import compute_status
from app.services.collector import classify
from app.services.poller import latest


def _poner_en_cache(device_id: int, pares, db=None) -> None:
    """Mete valores en la caché Y crea su métrica en el catálogo.

    Sin la fila del catálogo esto montaba un estado que no puede existir: el
    poller sondea lo que hay en el catálogo, así que todo lo que está en la caché
    tiene su fila. Y desde que compute_status ignora lo que no esté en el
    catálogo —para que borrar una métrica la quite del estado— el atajo deja de
    colar.
    """
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


def _equipo(db, nombre: str, ip: str) -> Device:
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d)
    db.commit()
    return d


# --------------------------------------------------------------------------
# De qué métrica sale la temperatura
# --------------------------------------------------------------------------
def test_dice_que_la_temperatura_es_la_de_entrada(db):
    d = _equipo(db, "con-entrada", "10.47.0.1")
    _poner_en_cache(d.id, [("temp_cpu", 68.0), ("temp_inlet", 23.0)], db)
    s = compute_status(d)
    assert s.temperature == 23.0
    assert s.temperature_metric == "temp_inlet"


def test_dice_que_ha_tenido_que_caer_a_la_cpu(db):
    """Sin esto, la interfaz pintaría 55 °C de CPU en la escala del aire y saldría
    rojo crítico cuando el equipo está tranquilo."""
    d = _equipo(db, "solo-cpu", "10.47.0.2")
    _poner_en_cache(d.id, [("temp_cpu", 55.0)], db)
    s = compute_status(d)
    assert s.temperature == 55.0
    assert s.temperature_metric == "temp_cpu"


def test_sin_ninguna_temperatura_no_inventa_metrica(db):
    d = _equipo(db, "sin-temperatura", "10.47.0.3")
    _poner_en_cache(d.id, [("fan_rpm", 3000.0)], db)
    s = compute_status(d)
    assert s.temperature is None
    assert s.temperature_metric is None


def test_una_temperatura_rara_tambien_se_nombra(db):
    d = _equipo(db, "escape", "10.47.0.4")
    _poner_en_cache(d.id, [("temp_exhaust", 41.0)], db)
    s = compute_status(d)
    assert s.temperature == 41.0
    assert s.temperature_metric == "temp_exhaust"


# --------------------------------------------------------------------------
# Qué entra en la media y en el ranking del resumen
# --------------------------------------------------------------------------
def test_la_media_del_resumen_ignora_los_equipos_que_solo_tienen_cpu(client, admin_headers, db):
    """Tres equipos con aire a 22-24 y uno con la CPU a 70. La media de la sala
    son los 22-24; meter el 70 la sube casi diez grados y no significa nada."""
    for i, t in enumerate((22.0, 23.0, 24.0), start=1):
        d = _equipo(db, f"aire-{i}", f"10.48.0.{i}")
        _poner_en_cache(d.id, [("temp_inlet", t)], db)
    cpu = _equipo(db, "solo-cpu-caliente", "10.48.0.9")
    _poner_en_cache(cpu.id, [("temp_cpu", 70.0)], db)

    r = client.get("/api/v1/overview", headers=admin_headers)
    assert r.status_code == 200
    datos = r.json()

    assert datos["avg_temperature"] == 23.0, "la CPU se ha colado en la media de la sala"
    assert datos["max_temperature"] == 24.0, "el pico de la sala es 24, no la CPU"

    # Pero el RANKING sí lo incluye. Esta prueba afirmaba lo contrario y estaba
    # mal: bastaba con que UN equipo tuviera sonda de aire para que todos los
    # demás desaparecieran de la única lista que se mira para saber qué está
    # caliente. El panel llegaba a decir "crítico: 1" y "máxima 24 °C" a la vez,
    # porque el crítico era un equipo sin sonda de aire y no salía por ningún
    # lado. Cada fila lleva su temperature_metric, así que la interfaz la pinta
    # en la escala que le toca.
    nombres = [h["device"]["name"] for h in datos["hottest"]]
    assert "solo-cpu-caliente" in nombres, (
        "un equipo sin sonda de aire ha desaparecido del ranking: invisible para el operador"
    )
    por_nombre = {h["device"]["name"]: h for h in datos["hottest"]}
    assert por_nombre["solo-cpu-caliente"]["temperature_metric"] == "temp_cpu", (
        "sin saber de qué métrica sale, la interfaz lo pintaría en la escala del aire"
    )


def test_el_ranking_ordena_por_estado_antes_que_por_grados(client, admin_headers, db):
    """Una CPU a 75 °C está en aviso; una entrada a 24 °C está normal. El que
    necesita atención va primero, aunque su número no sea el más grande."""
    aire = _equipo(db, "aire-templado", "10.52.0.1")
    _poner_en_cache(aire.id, [("temp_inlet", 24.0)], db)
    cpu = _equipo(db, "cpu-en-aviso", "10.52.0.2")
    _poner_en_cache(cpu.id, [("temp_cpu", 75.0)], db)

    r = client.get("/api/v1/overview", headers=admin_headers)
    orden = [h["device"]["name"] for h in r.json()["hottest"]]
    assert orden.index("cpu-en-aviso") < orden.index("aire-templado"), (
        "el equipo en aviso sale por debajo de uno que está perfectamente"
    )


def test_una_segunda_sonda_de_aire_se_juzga_como_aire(client, admin_headers, db):
    """temp_inlet_2 es aire, no un componente. Antes se juzgaba con la escala de
    CPU: un pasillo a 41 °C salía en verde, sin alerta y fuera del ranking."""
    from app.services.collector import es_de_entrada

    assert es_de_entrada("temp_inlet_2")
    assert es_de_entrada("temp_inlet2")
    assert es_de_entrada("temp_ambient_rear")
    assert not es_de_entrada("temp_cpu")
    assert not es_de_entrada("temp_inletfoo")

    d = _equipo(db, "dos-sondas", "10.53.0.1")
    _poner_en_cache(d.id, [("temp_inlet_2", 41.0)], db)
    s = compute_status(d)
    assert s.temperature == 41.0
    assert s.temperature_metric == "temp_inlet_2"
    assert s.status == "critical", (
        "41 °C de aire de entrada deberían ser críticos (ASHRAE: 32), no normales"
    )


def test_si_nadie_tiene_sensor_de_aire_se_usa_lo_que_haya(client, admin_headers, db):
    """Una instalación que aún no tiene sondas de entrada no puede quedarse con la
    pantalla en blanco."""
    for i, t in enumerate((55.0, 61.0), start=1):
        d = _equipo(db, f"cpu-{i}", f"10.49.0.{i}")
        _poner_en_cache(d.id, [("temp_cpu", t)], db)

    r = client.get("/api/v1/overview", headers=admin_headers)
    datos = r.json()
    assert datos["max_temperature"] == 61.0
    assert datos["avg_temperature"] == 58.0
    assert [h["device"]["name"] for h in datos["hottest"]][:1] == ["cpu-2"]


def test_el_resumen_dice_de_que_metrica_sale_cada_temperatura(client, admin_headers, db):
    d = _equipo(db, "para-la-interfaz", "10.50.0.1")
    _poner_en_cache(d.id, [("temp_inlet", 26.0)], db)

    r = client.get("/api/v1/devices/status", headers=admin_headers)
    assert r.status_code == 200
    fila = next(s for s in r.json() if s["device"]["name"] == "para-la-interfaz")
    assert fila["temperature_metric"] == "temp_inlet"


def test_el_informe_dice_de_que_sensor_sale_cada_fila(client, admin_headers, db):
    """El informe de SLA es el documento que el cliente enseña a su jefe. Sin esta
    marca, la interfaz pintaba una CPU a 55 °C en rojo de crítico en la misma fila
    que un «0 % sobre aviso»: el documento se contradecía solo."""
    from datetime import datetime, timedelta, timezone

    from app.models import MetricCatalog, MetricPoint

    ahora = datetime.now(timezone.utc)
    aire = _equipo(db, "con-aire", "10.54.0.1")
    cpu = _equipo(db, "solo-cpu-informe", "10.54.0.2")
    for d, nombre, valor in ((aire, "temp_inlet", 24.0), (cpu, "temp_cpu", 55.0)):
        m = MetricCatalog(device_id=d.id, name=nombre, label=nombre, unit="°C",
                          oid="1.2.3", poll_interval_s=30)
        db.add(m); db.commit()
        for i in range(5):
            db.add(MetricPoint(metric_id=m.id, device_id=d.id,
                               time=ahora - timedelta(minutes=i),
                               value=valor, status=classify(nombre, valor)))
    db.commit()

    r = client.get(
        "/api/v1/reports/adhoc",
        params={
            "fmt": "json",
            "from": (ahora - timedelta(hours=1)).isoformat(),
            "to": ahora.isoformat(),
        },
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    filas = {f["name"]: f for f in r.json()["per_device"]}
    assert filas["con-aire"]["sensor"] == "entrada"
    assert filas["solo-cpu-informe"]["sensor"] == "componente", (
        "una CPU marcada como aire se pintaría en rojo crítico a 55 °C"
    )
