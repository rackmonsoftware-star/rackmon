"""El SSO tiene que poder completar un inicio de sesion.

Hasta la 1.2.9 no podia, de ninguna manera. El flujo era:

  1. Login.tsx hace `window.location.href = authorization_url` — una navegacion
     de la ventana entera, no una peticion de API.
  2. El proveedor de identidad autentica y redirige EL NAVEGADOR al redirect_uri.
  3. `GET /api/v1/auth/oidc/callback` contestaba con `TokenPair`... en JSON.

Asi que el usuario terminaba mirando sus propios tokens en crudo sobre fondo
blanco, y la aplicacion no se enteraba de nada: en App.tsx no habia ninguna ruta
que recogiera ese resultado. SSO es una funcion de pago, cerrada tras un 403
"SSO requires a RackMon Pro license", y de las mas anunciadas. Un cliente que
pagaba la licencia Pro no podia entrar con ella.
"""
from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

from app.routers.auth import RUTA_DE_VUELTA_SSO
from app.services import sso

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _activar(db):
    from app.models import Setting

    db.merge(Setting(key="oidc", value={
        "enabled": True, "issuer": "https://idp.example.com",
        "client_id": "rackmon", "client_secret": "s3cret",
        "redirect_uri": "https://rackmon.example.com/api/v1/auth/oidc/callback",
        "authorization_endpoint": "https://idp.example.com/authorize",
        "token_endpoint": "https://idp.example.com/token",
    }))
    db.commit()


def test_el_callback_devuelve_al_navegador_a_la_aplicacion(client, db, monkeypatch):
    _activar(db)
    monkeypatch.setattr(sso, "exchange_code", lambda d, c: {"email": "u@corp.com"})
    state = client.get("/api/v1/auth/oidc/login").json()["state"]

    r = client.get(f"/api/v1/auth/oidc/callback?code=x&state={state}",
                   follow_redirects=False)

    assert r.status_code == 303, (
        "el callback no redirige: el navegador se queda donde esta, enseñando "
        "lo que devuelva el servidor"
    )
    assert urlparse(r.headers["location"]).path == RUTA_DE_VUELTA_SSO


def test_los_tokens_viajan_en_el_fragmento_y_no_en_la_consulta(client, db, monkeypatch):
    """El fragmento no se manda al servidor ni viaja en la cabecera Referer.

    En la consulta (?) acabarian en los registros de acceso del servidor web y en
    el Referer hacia cualquier tercero que la pagina cargue despues.
    """
    _activar(db)
    monkeypatch.setattr(sso, "exchange_code", lambda d, c: {"email": "u2@corp.com"})
    state = client.get("/api/v1/auth/oidc/login").json()["state"]

    r = client.get(f"/api/v1/auth/oidc/callback?code=x&state={state}",
                   follow_redirects=False)
    destino = urlparse(r.headers["location"])

    assert "access_token" not in (destino.query or ""), (
        "el token va en la consulta: termina en los registros de acceso"
    )
    frag = parse_qs(destino.fragment)
    assert frag.get("access_token") and frag.get("refresh_token")


def test_el_token_que_entrega_sirve_de_verdad(client, db, monkeypatch):
    _activar(db)
    monkeypatch.setattr(sso, "exchange_code", lambda d, c: {"email": "u3@corp.com"})
    state = client.get("/api/v1/auth/oidc/login").json()["state"]
    r = client.get(f"/api/v1/auth/oidc/callback?code=x&state={state}",
                   follow_redirects=False)
    token = parse_qs(urlparse(r.headers["location"]).fragment)["access_token"][0]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "u3@corp.com"


def test_la_cookie_de_estado_se_borra_en_la_propia_redireccion(client, db, monkeypatch):
    """Al devolver una respuesta nueva, lo que se hubiera puesto en la inyectada
    se queda por el camino. Un estado ya consumido no puede seguir vivo."""
    _activar(db)
    monkeypatch.setattr(sso, "exchange_code", lambda d, c: {"email": "u4@corp.com"})
    state = client.get("/api/v1/auth/oidc/login").json()["state"]

    r = client.get(f"/api/v1/auth/oidc/callback?code=x&state={state}",
                   follow_redirects=False)

    cookies = r.headers.get_list("set-cookie")
    assert any("oidc_state=" in c and ("Max-Age=0" in c or "expires=" in c.lower())
               for c in cookies), (
        f"la cookie de estado no se invalida en la redireccion: {cookies}"
    )


# --- el contrato con el frontend ------------------------------------------- #


def test_la_spa_tiene_la_ruta_que_recoge_el_resultado():
    """La mitad que faltaba, y la que nadie vigilaba.

    De poco sirve que el backend redirija bien si en el enrutador del frontend no
    hay nadie esperando en esa direccion: el comodin manda a /login y el inicio de
    sesion no se completa jamas. Esta prueba ata las dos mitades.
    """
    app_tsx = open(os.path.join(RAIZ, "frontend", "src", "App.tsx"), encoding="utf-8").read()
    assert f'path="{RUTA_DE_VUELTA_SSO}"' in app_tsx, (
        f"el backend manda el navegador a {RUTA_DE_VUELTA_SSO} y App.tsx no tiene "
        "esa ruta: el usuario acaba de vuelta en la pantalla de acceso"
    )
    # Y que este en la rama SIN sesion, que es donde se llega: en ese momento
    # todavia no hay sesion, la guarda precisamente esa pantalla.
    sin_sesion = app_tsx.split("if (!user)")[1].split("return (")[1]
    sin_sesion = sin_sesion[: sin_sesion.index("</Routes>")]
    assert f'path="{RUTA_DE_VUELTA_SSO}"' in sin_sesion, (
        "la ruta existe pero solo con sesion iniciada, que es justo lo que todavia "
        "no hay cuando el navegador vuelve del proveedor de identidad"
    )


def test_la_pantalla_de_vuelta_guarda_los_tokens_y_limpia_la_barra():
    ruta = os.path.join(RAIZ, "frontend", "src", "pages", "SsoCallback.tsx")
    assert os.path.exists(ruta), "no existe la pantalla que recoge el resultado del SSO"
    src = open(ruta, encoding="utf-8").read()
    assert "setTokens" in src, "recoge los tokens y no los guarda"
    assert re.search(r"location\.hash", src), "no lee el fragmento, que es donde llegan"
    assert "replaceState" in src, (
        "no limpia la barra de direcciones: los tokens se quedan a la vista"
    )
