"""El manifiesto es el unico canal que alcanza a quien ya tiene RackMon puesto.

`test_manifiesto_apunta_a_casa.py` comprueba que el aviso sale hacia el dominio
correcto. Esto comprueba lo otro: que lo que sale dentro no deja a nadie peor
que antes.

Dos defectos reales, los dos encontrados el 3-nov-2026 al revisar el manifiesto
de la 1.3.0 antes de publicarlo:

1. El canal `beta` llevaba congelada la 1.0.0 desde agosto, con las notas en
   blanco. Quien tuviera `updates.channel = "beta"` veia "ultima version 1.0.0"
   ejecutando la 1.3.0: tres versiones por detras de lo que ya tenia. No ofrecia
   una vuelta atras —`is_newer` lo impide— pero mostraba una cifra falsa en el
   panel, y un canal muerto que finge estar vivo es peor que no tenerlo.

2. El id del anuncio era `2026-11-02-rackmon-is-free-and-open-source-`. Ese
   guion final sale de `scripts/release.py`, que quitaba los separadores y
   DESPUES cortaba a 32 caracteres: si el corte cae en un separador, el
   separador se queda. El id lo guarda cada instalacion para recordar que ya
   vio el aviso, asi que sale en su base de datos y en sus registros.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest

from app.config import APP_VERSION
from app.services.updates import parse_semver

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFIESTO = os.path.join(RAIZ, "website", "updates", "manifest.json")

# `website/` esta en el .gitignore a proposito: ahi vive la clave de IndexNow,
# que no puede acabar publicada nunca. Asi que en un clon del repositorio
# publico —el CI, por ejemplo— el manifiesto no existe, y estas comprobaciones
# solo pueden correr en la maquina desde la que se publica.
#
# El salto se marca y se explica. La alternativa, dejarlas fallar en el CI, es
# peor; y la otra alternativa, sacar el manifiesto del .gitignore, acerca la
# clave de IndexNow a un `git add` descuidado, que es justo lo que no se puede
# permitir. Lo que SI se comprueba en cualquier clon es el generador de ids de
# `scripts/release.py`, que es donde estaba el defecto de verdad.
sin_sitio = pytest.mark.skipif(
    not os.path.isfile(MANIFIESTO),
    reason="website/ no esta en el repositorio publico (lleva la clave de IndexNow); "
    "el manifiesto solo se puede comprobar desde donde se publica",
)

# Las claves del manifiesto que NO son canales de version.
NO_SON_CANALES = {"_comment", "announcement"}


def _manifiesto() -> dict:
    with open(MANIFIESTO, encoding="utf-8") as fh:
        return json.load(fh)


def _canales(datos: dict) -> dict:
    return {
        nombre: nodo
        for nombre, nodo in datos.items()
        if nombre not in NO_SON_CANALES and isinstance(nodo, dict)
    }


def _release_py():
    """Carga scripts/release.py, que esta fuera del paquete del backend."""
    ruta = os.path.join(RAIZ, "scripts", "release.py")
    spec = importlib.util.spec_from_file_location("rackmon_release", ruta)
    assert spec and spec.loader, f"no puedo cargar {ruta}"
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@sin_sitio
def test_ningun_canal_anuncia_una_version_mas_vieja_que_la_del_producto():
    actual = parse_semver(APP_VERSION)
    atrasados = {
        nombre: nodo.get("version")
        for nombre, nodo in _canales(_manifiesto()).items()
        if parse_semver(str(nodo.get("version") or "0.0.0")) < actual
    }
    assert not atrasados, (
        f"el producto va por {APP_VERSION} y estos canales anuncian algo mas viejo: "
        f"{atrasados}. Quien los tenga elegido vera en su panel una cifra por "
        "detras de la que ya ejecuta."
    )


@sin_sitio
def test_cada_canal_dice_que_trae():
    sin_notas = [
        nombre
        for nombre, nodo in _canales(_manifiesto()).items()
        if not str(nodo.get("notes") or "").strip()
    ]
    assert not sin_notas, (
        f"canales sin notas: {sin_notas}. El panel pinta esas notas tal cual, asi "
        "que sin ellas el aviso es 'hay version nueva' y nada mas."
    )


@sin_sitio
def test_cada_canal_lleva_fecha_y_enlace():
    incompletos = {}
    for nombre, nodo in _canales(_manifiesto()).items():
        faltan = [c for c in ("version", "url", "published_at") if not nodo.get(c)]
        if faltan:
            incompletos[nombre] = faltan
    assert not incompletos, f"canales a medias: {incompletos}"


@sin_sitio
def test_el_id_del_anuncio_no_lleva_separadores_sueltos():
    anuncio = _manifiesto().get("announcement") or {}
    ident = str(anuncio.get("id") or "")
    assert ident, "el manifiesto no lleva anuncio"
    assert ident == ident.strip("-"), (
        f"el id del anuncio es {ident!r}. Ese separador suelto se guarda en la base "
        "de datos de cada instalacion que vea el aviso."
    )
    assert "--" not in ident, f"el id del anuncio lleva un separador doble: {ident!r}"


def test_el_generador_de_ids_corta_y_luego_limpia_no_al_contrario():
    """El orden importa: limpiar antes de cortar deja el corte sin limpiar."""
    anuncio_id = _release_py().announcement_id

    # Un titulo cuyo caracter 33 es justo un espacio: el corte cae en el
    # separador. Es el caso exacto que produjo el id de la 1.3.0.
    titulo = "RackMon is free and open source from 1.3.0"
    ident = anuncio_id("2026-11-03", titulo)
    assert ident == "2026-11-03-rackmon-is-free-and-open-source", ident

    # Y los extremos, con puntuacion a los dos lados.
    assert anuncio_id("2026-01-01", "  -- Hello, world! -- ") == "2026-01-01-hello-world"
