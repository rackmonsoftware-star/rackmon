"""Un equipo que deja de contestar tiene que avisar a alguien.

Era el agujero más grande que quedaba. El sondeador, al fallarle el sondeo de un
equipo, hacía esto:

    except Exception as exc:
        log.warning("poll failed for device %s: %s", device.id, exc)
        POLLS_TOTAL.labels(result="error").inc()
        continue            # <-- y aquí se acababa todo

Ese `continue` se saltaba también la llamada al motor de alertas. Y el motor solo
mira lecturas: de un equipo mudo no llega ninguna, así que no había condición que
evaluar, ni alerta, ni correo, ni Slack. La única señal era la tarjeta en gris en
el panel, para quien estuviera mirando la pantalla en ese preciso momento.

Peor: el informe de SLA —que es una función de pago y que un proveedor le entrega
firmada a su cliente— calcula la indisponibilidad sumando alertas críticas. Sin
alerta no hay indisponibilidad, así que un equipo muerto el mes entero salía con
un 100,000 % de disponibilidad.

La vía habitual de un equipo caído ni siquiera es una excepción: el colector SNMP
agota el tiempo OID por OID y devuelve la lista completa en NaN. Por eso el latido
no mira si `poll()` reventó, sino si ha llegado ALGUNA lectura aprovechable.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.models import Alert, AlertRule, Device, MetricCatalog
from app.services.collector import METRICA_ALCANZABLE, STATUS_MISSING, Reading
from app.services.seed import seed_all


def _equipo(db, nombre, ip):
    d = Device(name=nombre, ip=ip, enabled=True)
    db.add(d); db.commit()
    db.add(MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                         oid="1.1", scale=1.0, poll_interval_s=15))
    db.commit(); db.refresh(d)
    return d


def _instalacion_limpia(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()
    seed_all()
    # La regla de arranque espera 180 s de silencio continuado. En una prueba no
    # se esperan tres minutos: se comprueba aparte que ese valor es el publicado.
    for r in db.query(AlertRule).all():
        r.for_seconds = 0
    db.commit()


def test_la_instalacion_limpia_trae_regla_de_equipo_inalcanzable(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()
    seed_all()

    regla = db.query(AlertRule).filter(AlertRule.metric == METRICA_ALCANZABLE).one_or_none()
    assert regla is not None, (
        "ninguna regla vigila que un equipo siga contestando: puede morirse en "
        "silencio y el informe de SLA le dará un 100 % de disponibilidad"
    )
    assert regla.enabled is True
    assert regla.severity == "critical", (
        "mientras no contesta no sabemos su temperatura; eso no es «va bien»"
    )
    assert regla.for_seconds >= 60, (
        "sin ventana de persistencia, un tiempo de espera suelto despierta a "
        "alguien de madrugada y se acaba silenciando el monitor entero"
    )


@pytest.mark.parametrize("modo", ["excepcion", "todo_nan"])
def test_un_equipo_que_no_contesta_dispara_alerta(db, monkeypatch, modo):
    """Las dos formas de estar mudo: reventar y callar."""
    from app.services import poller as mod

    _instalacion_limpia(db, monkeypatch)
    d = _equipo(db, f"muerto-{modo}", "10.97.0.1")

    class Colector:
        def poll(self, device, metrics):
            if modo == "excepcion":
                raise RuntimeError("SNMP timeout")
            return [Reading(m.id, m.name, float("nan"), STATUS_MISSING, 0) for m in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    mod._last_polled.clear()
    mod._poll_once_sync()
    db.expire_all()

    alertas = db.query(Alert).filter(Alert.device_id == d.id).all()
    assert alertas, (
        f"el equipo lleva sin contestar ({modo}) y no se ha generado NADA: "
        "ni alerta, ni notificación, ni indisponibilidad en el informe de SLA"
    )
    a = alertas[0]
    assert a.severity == "critical"
    assert a.metric == METRICA_ALCANZABLE
    assert "unreachable" in (a.message or "").lower(), (
        f"el aviso dice «{a.message}»; quien lo recibe a las tres de la mañana "
        "tiene que entenderlo sin traducir nombres de métricas"
    )


def test_cuando_vuelve_a_contestar_la_alerta_se_cierra_sola(db, monkeypatch):
    from app.services import poller as mod

    _instalacion_limpia(db, monkeypatch)
    d = _equipo(db, "resucita", "10.97.0.2")

    contesta = {"si": False}

    class Colector:
        def poll(self, device, metrics):
            if not contesta["si"]:
                raise RuntimeError("SNMP timeout")
            return [Reading(m.id, m.name, 22.0, 0, 5) for m in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    mod._last_polled.clear()
    mod._poll_once_sync()
    db.expire_all()
    assert db.query(Alert).filter(Alert.device_id == d.id).count() == 1

    contesta["si"] = True
    # resolve_cycles = 2: hacen falta dos lecturas limpias seguidas.
    for _ in range(3):
        mod._last_polled.clear()
        mod._poll_once_sync()
    db.expire_all()

    a = db.query(Alert).filter(Alert.device_id == d.id).one()
    assert a.state == "resolved", (
        "el equipo volvió y la alerta sigue abierta: a la tercera, nadie mira ya "
        "la lista de alertas"
    )


def test_un_equipo_sano_no_genera_falsas_caidas(db, monkeypatch):
    """Que el latido no se convierta en una fábrica de ruido."""
    from app.services import poller as mod

    _instalacion_limpia(db, monkeypatch)
    d = _equipo(db, "sano", "10.97.0.3")

    class Colector:
        def poll(self, device, metrics):
            return [Reading(m.id, m.name, 22.0, 0, 5) for m in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    for _ in range(5):
        mod._last_polled.clear()
        mod._poll_once_sync()
    db.expire_all()

    assert db.query(Alert).filter(Alert.device_id == d.id).count() == 0


def test_el_latido_no_se_guarda_como_dato_del_equipo(db, monkeypatch):
    """No es una medida del equipo, es nuestra opinión sobre si contesta. No debe
    aparecer como una métrica más en el panel ni en las gráficas."""
    from app.services import poller as mod

    _instalacion_limpia(db, monkeypatch)
    d = _equipo(db, "sin-ruido", "10.97.0.4")

    class Colector:
        def poll(self, device, metrics):
            return [Reading(m.id, m.name, 22.0, 0, 5) for m in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    mod._last_polled.clear()
    mod._poll_once_sync()

    nombres = {x["metric"] for x in mod.latest.for_device(d.id)}
    assert METRICA_ALCANZABLE not in nombres, (
        "el latido se ha colado en la caché del panel y saldrá como una tarjeta más"
    )


def test_una_sonda_averiada_no_es_un_equipo_caido(db, monkeypatch):
    """La distinción que separa un aviso útil de un aviso falso.

    Una sonda rota devuelve el centinela del fabricante (-1, -99…). Esa lectura
    se descarta, y con razón, pero el equipo HA CONTESTADO: está vivo, en la red
    y respondiendo a SNMP. Si el latido se calculara sobre lo que acaba guardado
    en lugar de sobre lo que llegó, ese equipo saldría anunciado como caído.
    Avisar de una caída que no existe se paga igual de caro que no avisar de la
    de verdad: a la tercera, nadie mira los avisos.
    """
    from app.services import poller as mod

    _instalacion_limpia(db, monkeypatch)
    _equipo(db, "sonda-rota", "10.97.0.5")

    class Colector:
        def poll(self, device, metrics):
            # -1 es el "no disponible" documentado de CPQHLTH-MIB.
            return [Reading(m.id, m.name, -1.0, 0, 5) for m in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    for _ in range(3):
        mod._last_polled.clear()
        mod._poll_once_sync()
    db.expire_all()

    caidas = db.query(Alert).filter(Alert.metric == METRICA_ALCANZABLE).all()
    assert caidas == [], (
        "una sonda averiada se está anunciando como un equipo caído; el equipo "
        "contesta perfectamente y lo que falla es el sensor"
    )
