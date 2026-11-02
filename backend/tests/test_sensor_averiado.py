"""Una sonda averiada no puede salir como «la cosa más fría del rack».

El MIB de HPE (CPQHLTH) documenta -1 como «no disponible» para
cpqHeTemperatureCelsius. Otros fabricantes usan -99, -999 o el máximo del entero
con signo. El equipo RESPONDE —no hay error de SNMP— pero no sabe la respuesta.

Hasta ahora ese -1 se tomaba por una lectura buena: classify() lo veía por debajo
de 27 y lo marcaba NORMAL, el poller lo guardaba como un punto de -1 °C, el panel
lo pintaba en cian, el motor de alertas no decía nada, y la media de la sala
bajaba. Un producto que existe para avisar de que algo se calienta estaba
diciendo «todo en orden» justo cuando se había quedado ciego.
"""
from __future__ import annotations


import pytest

from app.services.collector import (
    STATUS_OK,
    classify,
    es_centinela,
    temperatura_creible,
)


@pytest.mark.parametrize("centinela", [-1.0, -99.0, -999.0, -32768.0, 32767.0, 65535.0])
def test_los_centinelas_de_fabricante_se_reconocen(centinela):
    assert es_centinela(centinela), f"{centinela} es un «no puedo leerlo», no una temperatura"


@pytest.mark.parametrize("real", [-5.0, 0.0, 18.3, 22.0, 27.0, 32.0, 55.0, 70.0, 95.0])
def test_una_lectura_de_verdad_no_se_confunde_con_un_centinela(real):
    assert not es_centinela(real)


def test_el_minus_uno_de_hpe_ya_no_pasa_por_normal():
    """El caso exacto: antes classify(-1) devolvía NORMAL."""
    assert classify("temp_inlet", -1.0) == STATUS_OK, (
        "classify sigue viendo -1 como normal — por eso hace falta filtrarlo ANTES"
    )
    assert es_centinela(-1.0), "y por eso nunca debe llegar a classify"


@pytest.mark.parametrize("imposible", [-40.0, -11.0, 151.0, 300.0, float("inf"), float("nan")])
def test_una_temperatura_imposible_no_es_creible(imposible):
    assert not temperatura_creible(imposible)


@pytest.mark.parametrize("posible", [-10.0, -5.0, 0.0, 5.0, 24.0, 32.0, 80.0, 110.0, 150.0])
def test_el_mundo_fisico_si_cabe(posible):
    """Una sala con free cooling en enero puede estar a 5 °C, y una CPU a 110
    antes de apagarse. No se puede ser tan estricto que se tiren datos buenos."""
    assert temperatura_creible(posible)


def test_el_centinela_escalado_tambien_cae():
    """iDRAC devuelve décimas: su -1 crudo se queda en -0,1 al escalar, y -0,1
    pasaría cualquier control de rango. Por eso se mira el crudo."""
    crudo = -1.0
    escalado = crudo * 0.1
    assert es_centinela(crudo), "el crudo tiene que cazarse antes de escalar"
    assert temperatura_creible(escalado), (
        "-0,1 °C es creíble en sí mismo: justo por eso el control de rango NO basta"
    )


def test_texto_o_none_se_tratan_como_no_leible():
    assert es_centinela(None)
    assert es_centinela("noSuchInstance")
    assert not temperatura_creible(None)
    assert not temperatura_creible("x")


# --------------------------------------------------------------------------
# De punta a punta: que el punto NO se guarde
# --------------------------------------------------------------------------
def test_una_lectura_imposible_no_llega_a_la_base_de_datos(db, monkeypatch):
    """La prueba que importa: un sensor averiado deja un HUECO en la gráfica, no
    un -1 °C que nadie cuestiona."""
    from app.models import Device, MetricCatalog, MetricPoint
    from app.services import poller as mod
    from app.services.collector import Reading

    d = Device(name="sonda-averiada", ip="10.70.0.1", enabled=True)
    db.add(d)
    db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", scale=1.0, poll_interval_s=15)
    db.add(m)
    db.commit()

    class ColectorAveriado:
        """Responde como un iLO con la sonda desconectada: -1, y sin error SNMP."""

        def poll(self, device, metrics):
            # status 0 = OK, que es justo lo que classify() devolvía para -1.
            return [Reading(mm.id, mm.name, -1.0, 0, 5) for mm in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: ColectorAveriado())
    mod._last_polled.clear()
    mod._poll_once_sync()

    puntos = db.query(MetricPoint).filter(MetricPoint.metric_id == m.id).all()
    assert not any(p.value == -1.0 for p in puntos), (
        "se ha guardado -1 °C como si fuera una temperatura real"
    )
    assert not puntos, "una lectura no creíble no debe dejar punto ninguno"


def test_una_lectura_buena_del_mismo_equipo_si_se_guarda(db, monkeypatch):
    """Que el filtro no se lleve por delante los datos buenos."""
    from app.models import Device, MetricCatalog, MetricPoint
    from app.services import poller as mod
    from app.services.collector import Reading

    d = Device(name="sonda-sana", ip="10.70.0.2", enabled=True)
    db.add(d)
    db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.3.6.1.4.1.232.6.2.6.8.1.4.1.1", scale=1.0, poll_interval_s=15)
    db.add(m)
    db.commit()

    class ColectorSano:
        def poll(self, device, metrics):
            return [Reading(mm.id, mm.name, 23.5, 0, 5) for mm in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: ColectorSano())
    mod._last_polled.clear()
    mod._poll_once_sync()

    puntos = db.query(MetricPoint).filter(MetricPoint.metric_id == m.id).all()
    assert any(abs(p.value - 23.5) < 1e-6 for p in puntos), "se ha perdido una lectura buena"


def test_un_sensor_que_se_rompe_NO_resuelve_una_alerta_viva(db, monkeypatch):
    """El fallo encadenado, y el peor de los dos.

    El motor de alertas recibe la lista de lecturas ENTERA, no la filtrada. Un -1
    descartado para guardar seguía llegándole como un número normal: no es NaN,
    así que no contaba como «falta el dato», la condición «-1 > 32» daba falso,
    subía la racha de limpieza y a los dos ciclos RESOLVÍA la alerta y mandaba un
    «recuperado».

    Traducido: el rack se está quemando, se le rompe la sonda, y RackMon avisa de
    que ya está todo bien. Es exactamente lo que el comentario del propio motor
    dice que nunca debe ocurrir.
    """
    from app.models import Alert, AlertRule, AlertState, Device, MetricCatalog
    from app.services import poller as mod
    from app.services.collector import Reading

    d = Device(name="rack-ardiendo", ip="10.71.0.1", enabled=True)
    db.add(d)
    db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.1", scale=1.0, poll_interval_s=15)
    regla = AlertRule(name="entrada crítica", scope_type="global", metric="temp_inlet",
                      operator=">", threshold=32.0, for_seconds=0,
                      severity="critical", throttle_seconds=600, enabled=True)
    db.add_all([m, regla])
    db.commit()

    valor = {"v": 40.0}

    class Colector:
        def poll(self, device, metrics):
            return [Reading(mm.id, mm.name, valor["v"], 0, 5) for mm in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())

    # 1. La sala se calienta de verdad: salta la alerta.
    mod._last_polled.clear()
    mod._poll_once_sync()
    viva = db.query(Alert).filter(Alert.device_id == d.id).first()
    assert viva is not None, "no ha saltado la alerta con 40 °C de entrada"
    assert viva.state == AlertState.firing.value

    # 2. Se rompe la sonda. Tantas vueltas como haría falta para resolverla.
    valor["v"] = -1.0
    for _ in range(5):
        mod._last_polled.clear()
        mod._poll_once_sync()

    db.expire_all()
    sigue = db.query(Alert).filter(Alert.device_id == d.id).first()
    assert sigue.state != AlertState.resolved.value, (
        "la alerta se ha resuelto sola porque el sensor se rompió: "
        "RackMon ha dicho «recuperado» con el rack ardiendo"
    )
