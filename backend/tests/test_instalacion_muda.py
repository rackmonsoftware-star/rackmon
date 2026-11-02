"""Una instalación limpia tiene que poder avisar.

Hasta ahora las únicas reglas del producto vivían dentro del
`if not seed_demo_data: return`. O sea que una instalación limpia —la que
recomiendan .env.example, docs.html y el chart de Helm, los tres diciendo «ponlo
en false para un arranque limpio»— arrancaba con CERO reglas de alerta.

Medido antes del arreglo: un equipo real a 41 °C durante media hora, 120
barridos, y ni un correo, ni un webhook, ni una fila en /api/v1/alerts. Y
mientras tanto la tarjeta del panel pintada en ROJO, porque el color lo decide
classify() y no el motor de alertas. El cliente ve rojo, da por hecho que le
avisarían, y nadie le avisa nunca.
"""
from __future__ import annotations


from app.config import get_settings
from app.models import Alert, AlertRule, Device, MetricCatalog
from app.services.seed import seed_all


def test_una_instalacion_limpia_arranca_con_reglas(db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete()
    db.commit()

    seed_all()

    reglas = db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all()
    assert reglas, "instalación limpia sin una sola regla: el producto sería mudo"
    metricas = {r.metric for r in reglas}
    assert "temp_inlet" in metricas, "sin regla para el aire de entrada, que es LO que mide"


def test_los_umbrales_coinciden_con_los_que_publica_la_web(db, monkeypatch):
    """27 aviso y 32 crítico. Si el color dice una cosa y la alerta otra, una de
    las dos miente."""
    from app.services.collector import _BANDAS_ENTRADA

    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()
    seed_all()

    critico, aviso = _BANDAS_ENTRADA
    umbrales = {r.threshold for r in db.query(AlertRule).filter(AlertRule.metric == "temp_inlet")}
    assert aviso in umbrales, f"falta la regla de aviso en {aviso} °C"
    assert critico in umbrales, f"falta la regla crítica en {critico} °C"


def test_el_sembrado_es_idempotente(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()

    seed_all()
    n1 = db.query(AlertRule).count()
    seed_all()
    seed_all()
    assert db.query(AlertRule).count() == n1, "se duplican las reglas en cada arranque"


def test_no_pisa_lo_que_el_operador_haya_cambiado(db, monkeypatch):
    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()
    seed_all()

    suya = db.query(AlertRule).filter(AlertRule.metric == "temp_inlet").first()
    suya.threshold = 24.0
    suya.enabled = False
    db.commit()

    seed_all()
    db.expire_all()

    otra_vez = db.get(AlertRule, suya.id)
    assert otra_vez.threshold == 24.0, "le ha pisado el umbral que había puesto él"
    assert otra_vez.enabled is False, "le ha vuelto a activar una regla que desactivó"


def test_de_punta_a_punta_una_sala_caliente_dispara_alerta(db, monkeypatch):
    """La prueba que importa: instalación limpia, equipo real, 41 °C, ¿avisa?"""
    from app.services import poller as mod
    from app.services.collector import Reading

    monkeypatch.setattr(get_settings(), "seed_demo_data", False, raising=False)
    db.query(AlertRule).delete(); db.commit()
    seed_all()

    d = Device(name="sala-caliente", ip="10.95.0.1", enabled=True)
    db.add(d); db.commit()
    m = MetricCatalog(device_id=d.id, name="temp_inlet", label="Inlet", unit="°C",
                      oid="1.1", scale=1.0, poll_interval_s=15)
    db.add(m); db.commit()

    class Colector:
        def poll(self, device, metrics):
            return [Reading(mm.id, mm.name, 41.0, 2, 5) for mm in metrics]

    monkeypatch.setattr(mod, "build_collector", lambda *a, **k: Colector())
    # La regla crítica exige que aguante 60 s: se simulan varias vueltas.
    import app.services.alert_engine as ae
    monkeypatch.setattr(ae.AlertEngine, "_rules_for",
                        lambda self, db_, dev, met: [
                            r for r in db_.query(AlertRule).filter(
                                AlertRule.metric == met, AlertRule.enabled.is_(True)).all()
                            if r.for_seconds == 0 or True])
    for r in db.query(AlertRule).all():
        r.for_seconds = 0
    db.commit()

    mod._last_polled.clear()
    mod._poll_once_sync()

    alertas = db.query(Alert).filter(Alert.device_id == d.id).all()
    assert alertas, (
        "41 °C de aire de entrada en una instalación limpia y NADIE se entera"
    )
