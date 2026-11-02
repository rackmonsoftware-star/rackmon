"""Una sola edicion, con todo dentro.

RackMon nacio como nucleo abierto: la monitorizacion gratis y seis cosas tras una
licencia de pago. El modelo se retiro el 1 de noviembre de 2026 por un motivo que
no admite discusion: **veintidos instalaciones y cero ventas**. Nadie llego nunca
a tener el problema de pagar.

Estas pruebas son las antiguas del reves. Antes habia un fichero entero
comprobando que SSO daba 403 sin licencia; ahora lo que se vigila es que **no se
cuele una puerta nueva**, porque es facil: basta con que alguien copie un
`if not has_feature(...)` de un ejemplo viejo y el producto vuelve a estar
cerrado sin que nadie se entere hasta que un usuario se queje.

Nota historica, para que no se pierda: hubo una licencia Pro perpetua firmada con
la clave real del vendedor publicada por error en el repositorio y en la imagen de
Docker (ver el changelog de 1.2.8). Con el producto abierto ya no desbloquea nada
-no hay nada que desbloquear-, asi que la revocacion y su prueba se retiraron con
el resto del andamiaje.
"""
from __future__ import annotations

import os
import re

import pytest

from app.services import licensing

RAIZ_APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))


# --- el modulo de licencias dice que si a todo -------------------------------


def test_la_edicion_lo_trae_todo():
    lic = licensing.get_license()
    assert lic.valid
    assert lic.features == licensing.ALL_FEATURES
    assert lic.max_devices is None, "sigue habiendo un tope de equipos"
    assert lic.expires_at is None, "la edicion caduca, y no deberia"


@pytest.mark.parametrize("f", sorted(licensing.ALL_FEATURES))
def test_todas_las_funciones_estan_disponibles(f):
    assert licensing.has_feature(f)
    assert licensing.get_license().has_feature(f)


def test_una_clave_vieja_en_el_env_no_molesta():
    """Quien tenga RACKMON_LICENSE_KEY puesto no tiene que ir a quitarlo."""
    for clave in ("", "   ", "basura", "eyJhbGciOiJub25lIn0.e30."):
        assert licensing.verify_license_key(clave).valid


# --- y el codigo no vuelve a cerrar nada -------------------------------------


def test_ningun_router_vuelve_a_poner_una_puerta():
    """La red: que no reaparezca un `if not has_feature(...)` copiado de un ejemplo."""
    culpables = []
    for base, _, ficheros in os.walk(os.path.join(RAIZ_APP, "routers")):
        if "__pycache__" in base:
            continue
        for n in ficheros:
            if not n.endswith(".py"):
                continue
            ruta = os.path.join(base, n)
            for i, linea in enumerate(open(ruta, encoding="utf-8"), 1):
                if re.search(r"if not .*has_feature", linea):
                    culpables.append(f"{n}:{i}: {linea.strip()}")
    assert not culpables, (
        "ha vuelto a aparecer una funcion cerrada tras licencia:\n  "
        + "\n  ".join(culpables)
    )


def test_nadie_responde_ya_pago_requerido():
    culpables = []
    for base, _, ficheros in os.walk(RAIZ_APP):
        if "__pycache__" in base or os.sep + "static" in base:
            continue
        for n in ficheros:
            if not n.endswith(".py"):
                continue
            ruta = os.path.join(base, n)
            for i, linea in enumerate(open(ruta, encoding="utf-8"), 1):
                if "PAYMENT_REQUIRED" in linea or "status_code=402" in linea:
                    culpables.append(f"{os.path.relpath(ruta, RAIZ_APP)}:{i}")
    assert not culpables, "algo vuelve a pedir dinero: " + ", ".join(culpables)


# --- de punta a punta: las seis que antes se pagaban --------------------------


def test_los_informes_de_sla_responden(client, admin_headers):
    r = client.get("/api/v1/reports/sla?fmt=json", headers=admin_headers)
    assert r.status_code == 200, f"el informe de SLA sigue cerrado ({r.status_code})"


def test_la_marca_personalizada_se_aplica(client, admin_headers):
    client.put("/api/v1/admin/settings/branding", headers=admin_headers,
               json={"value": {"product_name": "AcmeMon"}})
    assert client.get("/api/v1/branding").json()["product_name"] == "AcmeMon"


def test_sso_y_ldap_no_contestan_pago_requerido(client):
    """Apagados dan 404 (no configurados); lo que NO pueden dar es 403 por licencia."""
    for ruta in ("/api/v1/auth/oidc/login",):
        assert client.get(ruta).status_code != 403
    r = client.post("/api/v1/auth/ldap/login", json={"username": "x", "password": "y"})
    assert r.status_code != 403, "LDAP sigue pidiendo licencia"


def test_se_pueden_dar_de_alta_muchos_equipos(client, operator_headers):
    """Habia bandas de precio por numero de equipos. Ya no hay banda."""
    for n in range(40, 60):
        r = client.post("/api/v1/devices", headers=operator_headers, json={
            "name": f"equipo-{n}", "ip": f"10.44.0.{n}", "snmp_version": "2c",
            "snmp_community": "public",
        })
        assert r.status_code == 201, f"ha dejado de aceptar equipos en el {n}: {r.text[:120]}"


# --- y la interfaz tampoco ----------------------------------------------------


def _ficheros_del_frontend():
    raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                        "frontend", "src"))
    for base, dirs, ficheros in os.walk(raiz):
        dirs[:] = [d for d in dirs if d != "node_modules"]
        for n in ficheros:
            if n.endswith((".tsx", ".ts")):
                yield os.path.join(base, n), os.path.relpath(os.path.join(base, n), raiz)


def test_la_interfaz_no_marca_nada_como_de_pago():
    """Las puertas del backend se quitaron; las etiquetas de la interfaz no.

    Ajustes seguia pintando un distintivo "Pro" junto a la pagina de estado y a
    la marca blanca, e Informes junto al informe de SLA — tres funciones que ya
    vienen incluidas. Una pagina que dice "no hay edicion Pro" y una aplicacion
    que etiqueta tres cosas como Pro no pueden ser las dos verdad.
    """
    culpables = []
    for ruta, rel in _ficheros_del_frontend():
        for i, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if re.search(r'>\s*Pro\s*<|"Pro"|proFeatureLocked', linea):
                culpables.append(f"{rel}:{i}: {linea.strip()[:90]}")
    assert not culpables, (
        "la interfaz sigue marcando funciones como de pago:\n  " + "\n  ".join(culpables)
    )


def test_la_interfaz_no_esconde_nada_tras_la_lista_de_funciones():
    """Y no basta con quitar la etiqueta: el candado era peor que cosmetico.

    Las tres secciones se pintaban solo si `features.includes(...)` era cierto,
    con la lista traida de `GET /api/v1/license`. Esa peticion puede fallar —un
    corte de red, un 500, una sesion recien caducada— y entonces `features` se
    queda vacia y el usuario ve un candado de "funcion Pro" sobre algo que es
    suyo y gratuito. Ya no hay nada que consultar: se pinta siempre.
    """
    culpables = []
    for ruta, rel in _ficheros_del_frontend():
        for i, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            if re.search(r'features\.includes\(|hasSla\b', linea):
                culpables.append(f"{rel}:{i}: {linea.strip()[:90]}")
    assert not culpables, (
        "la interfaz sigue condicionando funciones a una lista de licencia:\n  "
        + "\n  ".join(culpables)
    )
