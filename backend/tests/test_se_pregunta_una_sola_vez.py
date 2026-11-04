"""RackMon pregunta una vez si puede buscar actualizaciones, y respeta la respuesta.

Por que existe esta pregunta. Hasta la 1.2.9 habia un fallo que dejaba leer
cualquier fichero que el proceso pudiera leer, sin tener cuenta — incluido el
entorno con la clave de firma. Se arreglo en la 1.2.10 y **no hubo forma de
avisar a nadie**: la comprobacion de actualizaciones venia apagada, asi que
ninguna instalacion pregunto nunca. El aviso salio por la descripcion de Docker
Hub, que no es un canal, es una esperanza.

Y por que se PREGUNTA en vez de encenderla y ya. RackMon se vende diciendo que
no llama a casa, y eso tiene que seguir siendo cierto: no sale una sola peticion
de la maquina hasta que un administrador responde.

Lo que vigilan estas pruebas es el equilibrio entre las dos cosas:

- que se pregunte cuando nadie ha respondido
- que **un "no" cuente como respuesta**. Si volviera a preguntar, seria una de
  esas ventanas que reaparecen hasta que cedes, y eso en un producto que se
  instala en el centro de datos de otro se paga caro.
- que nada salga al exterior antes de la respuesta
"""
from __future__ import annotations

from app.models import Setting
from app.services import updates


def _estado(client, headers) -> dict:
    return client.get("/api/v1/update-status", headers=headers).json()


def test_se_pregunta_cuando_nadie_ha_respondido(client, admin_headers):
    assert _estado(client, admin_headers)["decision_pending"] is True


def test_decir_que_si_la_enciende_y_no_vuelve_a_preguntar(client, admin_headers):
    r = client.put(
        "/api/v1/admin/settings/updates", headers=admin_headers, json={"value": {"enabled": True}}
    )
    assert r.status_code < 300, r.text
    cuerpo = _estado(client, admin_headers)
    assert cuerpo["decision_pending"] is False
    assert cuerpo["enabled"] is True


def test_decir_que_no_tambien_es_una_respuesta(client, admin_headers):
    """La que de verdad importa: un "no" tiene que callar la pregunta.

    Si siguiera preguntando seria una ventana que insiste hasta que cedes. En un
    producto autoalojado eso no es una molestia, es un motivo para desinstalarlo.
    """
    client.put(
        "/api/v1/admin/settings/updates", headers=admin_headers, json={"value": {"enabled": False}}
    )
    cuerpo = _estado(client, admin_headers)
    assert cuerpo["decision_pending"] is False, (
        "se ha respondido que no y RackMon vuelve a preguntar: eso es insistir"
    )
    assert cuerpo["enabled"] is False


def test_antes_de_responder_no_sale_nada_de_la_maquina(client, admin_headers, monkeypatch):
    """La promesa del producto: ni una peticion al exterior sin permiso."""
    llamadas = []
    monkeypatch.setattr(updates, "_fetch", lambda url: llamadas.append(url))
    _estado(client, admin_headers)
    assert llamadas == [], f"se llamo al exterior sin haber preguntado: {llamadas}"


def test_quien_no_es_administrador_no_decide(client, viewer_headers, admin_headers, db):
    """Un lector ve el estado, pero la respuesta la guarda un administrador.

    Se comprueba por donde se guarda, no por donde se lee: el endpoint de
    ajustes es el que tiene que negarse.
    """
    r = client.put(
        "/api/v1/admin/settings/updates", headers=viewer_headers, json={"value": {"enabled": True}}
    )
    assert r.status_code in (401, 403), f"un lector ha podido responder: {r.status_code}"
    assert updates.decision_pendiente(db) is True


def test_quien_lo_decide_por_entorno_no_recibe_la_pregunta(db, monkeypatch):
    """Instalacion desatendida: si viene decidido de fabrica, no hay nada que preguntar."""
    from app import config

    s = config.get_settings()
    monkeypatch.setattr(s, "update_check_enabled", True, raising=False)
    config.get_settings.cache_clear() if hasattr(config.get_settings, "cache_clear") else None
    monkeypatch.setattr(updates, "get_settings", lambda: s)
    assert updates.decision_pendiente(db) is False


def test_una_respuesta_a_medias_no_cuenta(db):
    """Guardar el canal o la URL no es responder a la pregunta.

    El ajuste `updates` guarda tres cosas. Si alguien toca solo el canal, sigue
    sin haber dicho si quiere que RackMon mire al exterior, y hay que preguntar.
    """
    db.add(Setting(key="updates", value={"channel": "beta"}))
    db.commit()
    assert updates.decision_pendiente(db) is True
