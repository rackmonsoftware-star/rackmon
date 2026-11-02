"""La API tiene que poder enseñar datos aunque no sea ella quien sondea.

`latest` vive en memoria del proceso y SOLO la escribe el poller. En el
despliegue por defecto del chart de Helm el poller va en su propio pod
(`api.pollerEnabled: false` + un Deployment aparte), así que los pods de la API
no tenían ni un valor: el panel, el mapa térmico, las medias y el ranking salían
vacíos de forma permanente mientras Postgres se llenaba de lecturas.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Device, MetricCatalog, MetricPoint
from app.routers.devices import compute_status
from app.services.poller import hidratar_desde_bd, latest


def _equipo_con_datos(db, nombre, ip, valor=26.5, hace_s=5):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.1", scale=1.0, poll_interval_s=30)
    db.add(m); db.commit()
    ahora = datetime.now(timezone.utc)
    for i in range(3):
        db.add(MetricPoint(metric_id=m.id, device_id=d.id,
                           time=ahora - timedelta(seconds=hace_s + i * 15),
                           value=valor - i, status=0))
    db.commit(); db.refresh(d)
    return d


def test_sin_cache_el_panel_sale_vacio(db):
    """El punto de partida: así estaba un pod de API en Kubernetes."""
    d = _equipo_con_datos(db, "api-sin-poller", "10.98.0.1")
    latest._data.clear()

    s = compute_status(d)
    assert s.temperature is None and s.status == "nodata"


def test_al_hidratar_desde_la_bd_el_panel_vuelve(db):
    d = _equipo_con_datos(db, "api-hidratada", "10.98.0.2", valor=26.5)
    latest._data.clear()

    puestos = hidratar_desde_bd()

    assert puestos > 0, "no ha cargado nada de la base de datos"
    s = compute_status(d)
    assert s.temperature == 26.5, "no ha cogido la lectura MÁS RECIENTE"
    assert s.status == "ok"
    assert s.temperature_metric == "temp_inlet"


def test_coge_la_mas_reciente_de_cada_metrica(db):
    """Ordena por tiempo ascendente para que gane la última, no una cualquiera."""
    d = _equipo_con_datos(db, "varias-lecturas", "10.98.0.3", valor=30.0)
    latest._data.clear()
    hidratar_desde_bd()
    assert compute_status(d).temperature == 30.0


def test_lo_viejo_fuera_de_la_ventana_no_resucita(db):
    """Una lectura de hace horas no debe volver a dar por vivo a un equipo."""
    d = _equipo_con_datos(db, "callado-hace-rato", "10.98.0.4", hace_s=7200)
    latest._data.clear()

    hidratar_desde_bd(ventana_s=900)

    s = compute_status(d)
    assert s.status == "nodata", "una lectura de hace dos horas lo ha dado por sano"
