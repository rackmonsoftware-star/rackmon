"""La retención a cero no puede significar «bórralo todo».

`raw_retention_days` por defecto es 30. Con 0 el corte quedaba en «ahora» y la
limpieza se llevaba el histórico entero —incluidos los puntos de hace un
segundo— cada hora y sin preguntar. Y 0 es exactamente lo que escribe quien
quiere decir «sin límite»: es la convención en casi todas las herramientas del
ramo. Quien buscaba conservarlo todo se quedaba sin nada.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.models import Device, MetricCatalog, MetricPoint
from app.services.scheduler import prune_raw_points


def _con_puntos(db, nombre, ip, edades_dias):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.1", scale=1.0, poll_interval_s=30)
    db.add(m); db.commit()
    ahora = datetime.now(timezone.utc)
    for i, dias in enumerate(edades_dias):
        db.add(MetricPoint(metric_id=m.id, device_id=d.id,
                           time=ahora - timedelta(days=dias, seconds=i),
                           value=22.0 + i, status=0))
    db.commit()
    return m


@pytest.mark.parametrize("dias", [0, -1, -30])
def test_cero_o_menos_no_borra_nada(db, monkeypatch, dias):
    m = _con_puntos(db, f"sin-limite-{dias}", f"10.80.{abs(dias)}.1", [0, 1, 45, 400])
    monkeypatch.setattr(get_settings(), "raw_retention_days", dias, raising=False)

    borrados = prune_raw_points()

    assert borrados == 0, f"con retención {dias} se han borrado {borrados} puntos"
    assert db.query(MetricPoint).filter(MetricPoint.metric_id == m.id).count() == 4


def test_con_un_limite_de_verdad_si_borra_lo_viejo(db, monkeypatch):
    """Que el arreglo no haya desactivado la limpieza."""
    m = _con_puntos(db, "con-limite", "10.80.9.1", [0, 1, 45, 400])
    monkeypatch.setattr(get_settings(), "raw_retention_days", 30, raising=False)

    borrados = prune_raw_points()

    assert borrados == 2, "deberían caer los de 45 y 400 días"
    quedan = db.query(MetricPoint).filter(MetricPoint.metric_id == m.id).count()
    assert quedan == 2, "y quedarse los de hoy y ayer"
