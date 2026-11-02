"""Nadie puede leer ficheros del servidor sin tener cuenta.

El comodin que sirve la aplicacion web hacia esto:

    candidate = STATIC_DIR / full_path
    if candidate.is_file():
        return FileResponse(candidate)

Juntar rutas con "/" NO normaliza los "..", pero el sistema operativo si los
resuelve al comprobar si el fichero existe. Starlette descodifica el parametro de
ruta antes de entregarlo, asi que una peticion a `/%2e%2e/%2e%2e/.env` llegaba
aqui como "../../.env", salia del directorio y devolvia el fichero con un 200.

Sin cuenta. Sin token. Sin dejar mas rastro que una linea de acceso corriente.

Lo que quedaba al alcance de cualquiera que supiera la direccion de una
instalacion: el `.env` con RACKMON_JWT_SECRET y RACKMON_MASTER_KEY —con eso se
firma un token de administrador y se descifran todas las credenciales SNMP
guardadas—, la base de datos entera, y cualquier fichero legible por el proceso.
"""
from __future__ import annotations

import pytest

from app.main import STATIC_DIR

# Las formas de escribir "sube un directorio" que un servidor puede dejar pasar.
ESCAPES = [
    "%2e%2e/%2e%2e/{f}",
    "..%2f..%2f{f}",
    "%2e%2e%2f%2e%2e%2f{f}",
    "..%252f..%252f{f}",
    "%2e%2e/%2e%2e/%2e%2e/%2e%2e/{f}",
]


@pytest.fixture()
def secreto(tmp_path_factory):
    """Un fichero fuera de static, como lo seria el .env de una instalacion."""
    f = STATIC_DIR.parent.parent / "SECRETO_DE_PRUEBA.txt"
    f.write_text("RACKMON_JWT_SECRET=no-deberia-salir-jamas", encoding="utf-8")
    yield f
    f.unlink(missing_ok=True)


@pytest.mark.parametrize("plantilla", ESCAPES)
def test_no_se_puede_salir_del_directorio_publico(client, secreto, plantilla):
    r = client.get("/" + plantilla.format(f=secreto.name))
    assert "no-deberia-salir-jamas" not in r.text, (
        f"{plantilla!r} devuelve un fichero de fuera de static, sin autenticar: "
        "con el .env de una instalacion real eso es firmar tokens de administrador "
        "y descifrar todas sus credenciales SNMP"
    )


def test_tampoco_con_una_ruta_absoluta(client, secreto):
    r = client.get(f"/{secreto.name}")
    assert "no-deberia-salir-jamas" not in r.text


def test_un_fichero_de_dentro_si_se_sirve(client):
    """Que el arreglo no rompa la aplicacion: index.html tiene que seguir saliendo."""
    r = client.get("/index.html")
    assert r.status_code == 200
    assert "<" in r.text


def test_una_ruta_de_la_spa_sigue_devolviendo_la_aplicacion(client):
    """Las rutas del enrutador del navegador no son ficheros y deben dar index.html."""
    r = client.get("/devices")
    assert r.status_code == 200


def test_las_rutas_de_api_que_no_existen_siguen_dando_404(client):
    assert client.get("/api/v1/no-existe").status_code == 404


def test_un_enlace_simbolico_hacia_fuera_tampoco_vale(client, secreto):
    """resolve() sigue los enlaces, asi que colar uno dentro de static no sirve."""
    import os

    enlace = STATIC_DIR / "atajo-de-prueba.txt"
    try:
        os.symlink(secreto, enlace)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("este sistema no deja crear enlaces simbolicos sin permisos")
    try:
        r = client.get("/atajo-de-prueba.txt")
        assert "no-deberia-salir-jamas" not in r.text, (
            "un enlace simbolico dentro de static saca ficheros de fuera"
        )
    finally:
        try:
            enlace.unlink()
        except OSError:
            pass
