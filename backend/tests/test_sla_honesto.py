"""El informe de disponibilidad es lo que un proveedor le entrega a su cliente.

Es la función de pago más delicada que tiene el producto: no es una gráfica que
mira un técnico, es un número con el que alguien justifica una factura o reclama
una penalización. Tenía tres formas de mentir, todas hacia el lado cómodo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Alert, AlertState, Device
from app.services.sla import compute_sla_report


def _equipo(db, nombre, ip):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit(); db.refresh(d)
    return d


def _caida(db, dev, desde, hasta=None):
    a = Alert(rule_id=None, device_id=dev.id, metric="device_reachable",
              severity="critical", state=AlertState.firing.value, value=0.0,
              message="Device unreachable", started_at=desde)
    if hasta is not None:
        a.state = AlertState.resolved.value
        a.ended_at = hasta
        a.resolved_at = hasta
    db.add(a); db.commit()
    return a


def test_el_futuro_no_cuenta_como_tiempo_en_servicio(db):
    """Pedir el mes entero el día 14 daba 17 días de regalo."""
    ahora = datetime.now(timezone.utc)
    d = _equipo(db, "caido-del-todo", "10.98.0.1")
    _caida(db, d, ahora - timedelta(days=14))   # sigue caído

    r = compute_sla_report(db, ahora - timedelta(days=14), ahora + timedelta(days=17))

    disp = r["per_device"][0]["availability_pct"]
    assert disp < 1.0, (
        f"lleva 14 días caído y el informe dice {disp} % porque cuenta como "
        "tiempo en servicio 17 días que todavía no han ocurrido"
    )


def test_un_periodo_al_reves_no_devuelve_un_cien_por_cien(db):
    ahora = datetime.now(timezone.utc)
    d = _equipo(db, "lo-que-sea", "10.98.0.2")
    _caida(db, d, ahora - timedelta(days=5))

    with pytest.raises(ValueError):
        compute_sla_report(db, ahora, ahora - timedelta(days=30))


def test_el_porcentaje_publicado_y_el_veredicto_no_se_contradicen(db):
    """Un equipo justo por debajo del objetivo salía impreso como «99.9 %» y
    «MISS» contra un objetivo de 99,9 %."""
    ahora = datetime.now(timezone.utc)
    inicio = ahora - timedelta(days=30)
    d = _equipo(db, "al-filo", "10.98.0.3")
    # 30 días = 2 592 000 s. Una caída de 2597 s deja la disponibilidad en
    # 99,899807 %: por debajo del objetivo en crudo, pero redondeada a los tres
    # decimales que se publican es exactamente 99.9. Ese es el hueco.
    _caida(db, d, inicio + timedelta(days=1),
           inicio + timedelta(days=1, seconds=2597))

    r = compute_sla_report(db, inicio, ahora, target_pct=99.9)
    fila = r["per_device"][0]

    assert fila["availability_pct"] == 99.9, "la prueba ya no cae en el borde"
    assert fila["sla_met"], (
        "el informe imprime 99.9 % y a su lado un «MISS» contra un objetivo de "
        "99.9 %: el cliente que lo lee deja de fiarse del resto"
    )


def test_una_caida_real_si_se_descuenta(db):
    """Que el arreglo no se haya llevado por delante la cuenta de verdad."""
    ahora = datetime.now(timezone.utc)
    inicio = ahora - timedelta(hours=10)
    d = _equipo(db, "una-hora-fuera", "10.98.0.4")
    _caida(db, d, inicio + timedelta(hours=1), inicio + timedelta(hours=2))

    r = compute_sla_report(db, inicio, ahora)
    fila = r["per_device"][0]
    assert 59.0 <= fila["downtime_minutes"] <= 61.0
    assert 89.0 <= fila["availability_pct"] <= 91.0
    assert fila["incidents"] == 1
