"""El `docker compose up` del README tiene que poder arrancar.

Es el primer comando que ejecuta cualquiera que clone esto, y durante un tiempo
no funcionaba. `docker-compose.yml` fija `RACKMON_ENVIRONMENT: production` a
mano, y en producción RackMon se niega a arrancar mientras alguno de sus
secretos siga siendo el de fábrica. El fichero reenviaba `RACKMON_JWT_SECRET` y
`RACKMON_MASTER_KEY` pero **no** `RACKMON_ADMIN_PASSWORD`, así que esa se
quedaba en la de fábrica y el guardián abortaba el arranque. Con
`restart: unless-stopped`, el contenedor entraba en bucle de reinicio y Caddy
devolvía 502.

Lo que lo hacía difícil de ver: ponerla en el `.env` no arreglaba nada. Compose
usa el `.env` para sustituir `${...}` dentro del propio fichero, no lo inyecta en
el contenedor; y `.env` está en el `.dockerignore`, así que pydantic tampoco lo
encontraba dentro de la imagen. La única salida era editar el compose, y el
README no lo pedía.

La prueba lee el compose de verdad y comprueba que todo servicio que se declare
en producción reenvíe las variables que el guardián audita. No depende de la
lista: la saca de `config.py`, así que añadir un secreto nuevo al guardián hace
fallar esto hasta que el compose lo reenvíe también.
"""
from __future__ import annotations

import os
import re

import pytest

yaml = pytest.importorskip("yaml")

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSES = ("docker-compose.yml", "docker-compose.sqlite.yml")


def _vigiladas() -> set[str]:
    """Los nombres que `production_safety_check` audita, leídos del fuente."""
    ruta = os.path.join(RAIZ, "backend", "app", "config.py")
    with open(ruta, encoding="utf-8") as fh:
        texto = fh.read()
    m = re.search(r'for name in \(([^)]*)\):', texto, re.S)
    assert m, "no encuentro la lista de secretos que audita el guardian"
    return {"RACKMON_" + n.upper() for n in re.findall(r'"([a-z_]+)"', m.group(1))}


def _servicios(fichero: str):
    ruta = os.path.join(RAIZ, fichero)
    if not os.path.exists(ruta):
        return {}
    with open(ruta, encoding="utf-8") as fh:
        datos = yaml.safe_load(fh)
    return (datos or {}).get("services", {}) or {}


@pytest.mark.parametrize("fichero", COMPOSES)
def test_en_produccion_el_compose_pasa_todo_lo_que_el_guardian_exige(fichero):
    vigiladas = _vigiladas()
    assert vigiladas, "la lista de secretos vigilados salio vacia"

    for nombre, servicio in _servicios(fichero).items():
        entorno = (servicio or {}).get("environment") or {}
        if isinstance(entorno, list):  # forma "CLAVE=valor"
            entorno = dict(e.split("=", 1) for e in entorno if "=" in e)
        if str(entorno.get("RACKMON_ENVIRONMENT", "")).strip() != "production":
            continue
        faltan = sorted(v for v in vigiladas if v not in entorno)
        assert not faltan, (
            f"{fichero}: el servicio {nombre!r} declara RACKMON_ENVIRONMENT=production "
            f"pero no reenvia {', '.join(faltan)}. En produccion RackMon se niega a "
            "arrancar con el valor de fabrica, asi que `docker compose up` no levanta "
            "y ponerlas en el .env no sirve: Compose no lo inyecta en el contenedor."
        )


@pytest.mark.parametrize("fichero", COMPOSES)
def test_los_secretos_obligatorios_fallan_claro_si_faltan(fichero):
    """`${VAR:?...}` para que Compose diga cuál falta en vez de arrancar roto."""
    ruta = os.path.join(RAIZ, fichero)
    if not os.path.exists(ruta):
        pytest.skip(f"{fichero} no esta en este arbol")
    with open(ruta, encoding="utf-8") as fh:
        crudo = fh.read()
    for var in _vigiladas():
        if f"{var}:" not in crudo:
            continue
        linea = next(l for l in crudo.splitlines() if l.strip().startswith(f"{var}:"))
        assert ":?" in linea or ":-" in linea or "${" not in linea, (
            f"{fichero}: {var} se interpola sin valor por defecto ni mensaje de error; "
            "si el operador la olvida, el contenedor arranca con la cadena vacia"
        )


def test_el_readme_no_promete_una_cuenta_que_el_compose_no_crea():
    """La tabla de credenciales vale para el arranque local, no para el compose."""
    with open(os.path.join(RAIZ, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    inicio = readme.find("## Quick start")
    fin = readme.find("##", inicio + 5)
    arranque = readme[inicio:fin]
    assert "demo account below" not in arranque, (
        "el arranque rapido manda entrar con la cuenta de la tabla de credenciales, "
        "y el compose corre en produccion: esa cuenta no se crea nunca por esa via"
    )
    assert "RACKMON_ADMIN_PASSWORD" in arranque, (
        "el arranque rapido no dice que hay que fijar RACKMON_ADMIN_PASSWORD, "
        "sin la cual `docker compose up` no levanta"
    )


def test_el_chart_de_helm_pasa_lo_mismo_al_pod():
    """El mismo fallo, en el otro camino de despliegue.

    `deploy/helm/rackmon/values.yaml` fija `config.environment: production`, y
    el Secret solo llevaba JWT_SECRET, MASTER_KEY y DB_PASSWORD. El pod se
    negaba a arrancar por la contrasena de administrador de fabrica, y
    `helm install --wait` agotaba sus cinco minutos sin explicar nada — incluido
    el trabajo de Kubernetes del CI, que corre en cada push.
    """
    base = os.path.join(RAIZ, "deploy", "helm", "rackmon")
    if not os.path.isdir(base):
        pytest.skip("el chart no esta en este arbol")

    with open(os.path.join(base, "values.yaml"), encoding="utf-8") as fh:
        valores = yaml.safe_load(fh)
    if str((valores.get("config") or {}).get("environment", "")) != "production":
        pytest.skip("el chart no despliega en produccion")

    with open(os.path.join(base, "templates", "config.yaml"), encoding="utf-8") as fh:
        plantilla = fh.read()
    with open(os.path.join(base, "templates", "api.yaml"), encoding="utf-8") as fh:
        api = fh.read()

    for var in sorted(_vigiladas()):
        assert var in plantilla, (
            f"el chart despliega en produccion pero su Secret no define {var}: "
            "el pod no arrancaria nunca"
        )
        assert var in api, (
            f"{var} esta en el Secret pero el contenedor no lo lee: api.yaml "
            "nombra las claves una a una con secretKeyRef, asi que anadirla al "
            "Secret no basta"
        )
