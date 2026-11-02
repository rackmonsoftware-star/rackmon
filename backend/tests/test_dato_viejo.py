"""Un equipo que dejó de responder no puede seguir pintado en verde.

`latest` es una caché en memoria que guarda el último valor para siempre. Si un
equipo se apaga o se queda sin red, su última lectura se queda ahí y el panel lo
sigue dando por sano. Medido: un valor de hace TRES DÍAS seguía saliendo como
«ok, 24 °C». Es la mentira más cómoda que puede contar un monitor — y la que
hace que nadie vaya a mirar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Device, MetricCatalog
from app.routers.devices import compute_status
from app.services.poller import latest


def _equipo(db, nombre, ip, intervalo=30):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit()
    db.add(MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                         oid="1.1", scale=1.0, poll_interval_s=intervalo))
    db.commit(); db.refresh(d)
    return d


@pytest.mark.parametrize("antiguedad_h", [1, 24, 72])
def test_un_valor_viejo_no_cuenta_como_sano(db, antiguedad_h):
    d = _equipo(db, f"callado-{antiguedad_h}", f"10.96.{antiguedad_h}.1")
    viejo = datetime.now(timezone.utc) - timedelta(hours=antiguedad_h)
    latest.update(d.id, "temp_inlet", 24.0, 0, viejo, "°C")

    s = compute_status(d)

    assert s.status == "nodata", (
        f"un dato de hace {antiguedad_h} h sigue saliendo como «{s.status}»"
    )


def test_un_valor_reciente_si_cuenta(db):
    """Que el margen no se lleve por delante lo que está vivo."""
    d = _equipo(db, "al-dia", "10.96.0.9")
    latest.update(d.id, "temp_inlet", 24.0, 0, datetime.now(timezone.utc), "°C")
    assert compute_status(d).status == "ok"


def test_saltarse_un_ciclo_no_lo_marca_caido(db):
    """Tolerancia: tres veces el intervalo. Un sondeo que se retrasa no es una
    caída, y marcarlo como tal enseña a la gente a ignorar el panel."""
    d = _equipo(db, "un-poco-tarde", "10.96.0.10", intervalo=30)
    hace_poco = datetime.now(timezone.utc) - timedelta(seconds=45)
    latest.update(d.id, "temp_inlet", 24.0, 0, hace_poco, "°C")
    assert compute_status(d).status == "ok"


def test_un_intervalo_lento_tiene_mas_margen(db):
    """Una métrica cada 10 min no puede darse por caída a los 90 s."""
    d = _equipo(db, "lento", "10.96.0.11", intervalo=600)
    hace_cinco_min = datetime.now(timezone.utc) - timedelta(minutes=5)
    latest.update(d.id, "temp_inlet", 24.0, 0, hace_cinco_min, "°C")
    assert compute_status(d).status == "ok"
