"""Borrar una métrica del catálogo tiene que quitarla del estado.

`latest` es una caché en memoria y no se entera de los borrados. El operador veía
un temp_inlet mal configurado marcando 275 °C —el clásico «décimas sin escalar»—,
lo borraba del catálogo para quitarse el problema, y el equipo seguía en rojo
crítico con 275 °C indefinidamente. La única salida era reiniciar el proceso, y
nada en la pantalla lo decía.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models import Device, MetricCatalog
from app.routers.devices import compute_status
from app.services.poller import latest


def _equipo(db, nombre, ip):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.1", scale=1.0, poll_interval_s=30)
    db.add(m); db.commit(); db.refresh(d)
    return d, m


def test_al_borrar_la_metrica_deja_de_mandar_en_el_estado(db):
    d, m = _equipo(db, "mal-configurado", "10.97.0.1")
    latest.update(d.id, "temp_inlet", 275.0, 2, datetime.now(timezone.utc), "°C")
    assert compute_status(d).status == "critical", "punto de partida: está en rojo"

    db.delete(m)
    db.commit()
    db.refresh(d)

    s = compute_status(d)
    assert s.temperature != 275.0, "sigue enseñando la temperatura de una métrica borrada"
    assert s.status != "critical", "sigue en rojo por una métrica que ya no existe"


def test_borrar_una_de_dos_deja_la_otra(db):
    """Que no se lleve por delante lo que sí sigue vigente."""
    d, inlet = _equipo(db, "dos-metricas", "10.97.0.2")
    cpu = MetricCatalog(device_id=d.id, name="temp_cpu", label="CPU", unit="°C",
                        oid="1.2", scale=1.0, poll_interval_s=30)
    db.add(cpu); db.commit(); db.refresh(d)

    ahora = datetime.now(timezone.utc)
    latest.update(d.id, "temp_inlet", 275.0, 2, ahora, "°C")
    latest.update(d.id, "temp_cpu", 55.0, 0, ahora, "°C")

    db.delete(inlet); db.commit(); db.refresh(d)

    s = compute_status(d)
    assert s.temperature == 55.0, "se ha perdido la métrica que sigue en el catálogo"
    assert s.temperature_metric == "temp_cpu"
