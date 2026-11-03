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
README no lo pedía. El chart de Helm tenía el mismo agujero, lo que además hacía
fallar el trabajo de Kubernetes en cada ejecución del CI.

La lista de secretos no está escrita aquí: se lee de `config.py`, así que añadir
uno nuevo al guardián hace fallar esto hasta que el compose y el chart lo
reenvíen también.

Sin PyYAML a propósito: no es dependencia del proyecto, y una prueba que se salta
sola en CI —que es justo donde haría falta— no protege de nada.
"""
from __future__ import annotations

import os
import re

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COMPOSES = ("docker-compose.yml", "docker-compose.sqlite.yml")


def _lee(*partes: str) -> str | None:
    ruta = os.path.join(RAIZ, *partes)
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()


def _vigiladas() -> set[str]:
    """Los nombres que `production_safety_check` audita, leídos del fuente."""
    texto = _lee("backend", "app", "config.py")
    assert texto, "no encuentro config.py"
    m = re.search(r"for name in \(([^)]*)\):", texto, re.S)
    assert m, "no encuentro la lista de secretos que audita el guardian"
    nombres = {"RACKMON_" + n.upper() for n in re.findall(r'"([a-z_]+)"', m.group(1))}
    assert nombres, "la lista de secretos vigilados salio vacia"
    return nombres


def _declara_produccion(texto: str) -> bool:
    return bool(re.search(r"^\s*(RACKMON_ENVIRONMENT|environment):\s*[\"']?production", texto, re.M))


def test_en_produccion_el_compose_pasa_todo_lo_que_el_guardian_exige():
    for fichero in COMPOSES:
        texto = _lee(fichero)
        if texto is None or not _declara_produccion(texto):
            continue
        faltan = sorted(v for v in _vigiladas() if not re.search(rf"^\s*{v}:", texto, re.M))
        assert not faltan, (
            f"{fichero} declara RACKMON_ENVIRONMENT=production pero no reenvia "
            f"{', '.join(faltan)}. En produccion RackMon se niega a arrancar con el "
            "valor de fabrica, asi que `docker compose up` no levanta — y ponerlas en "
            "el .env no sirve, porque Compose no lo inyecta en el contenedor."
        )


def test_los_secretos_obligatorios_fallan_claro_si_faltan():
    """`${VAR:?...}` para que Compose diga cuál falta en vez de arrancar roto."""
    for fichero in COMPOSES:
        texto = _lee(fichero)
        if texto is None:
            continue
        for var in _vigiladas():
            for linea in texto.splitlines():
                if not linea.strip().startswith(f"{var}:") or "${" not in linea:
                    continue
                assert ":?" in linea or ":-" in linea, (
                    f"{fichero}: {var} se interpola sin valor por defecto ni mensaje "
                    "de error; si el operador la olvida, el contenedor arranca con la "
                    "cadena vacia en vez de decirlo"
                )


def test_el_chart_de_helm_pasa_lo_mismo_al_pod():
    """El mismo fallo, en el otro camino de despliegue — y en el CI."""
    valores = _lee("deploy", "helm", "rackmon", "values.yaml")
    plantilla = _lee("deploy", "helm", "rackmon", "templates", "config.yaml")
    api = _lee("deploy", "helm", "rackmon", "templates", "api.yaml")
    if valores is None or plantilla is None or api is None:
        return  # el chart no esta en este arbol
    if not _declara_produccion(valores):
        return

    for var in sorted(_vigiladas()):
        assert var in plantilla, (
            f"el chart despliega en produccion pero su Secret no define {var}: "
            "el pod no arrancaria nunca y `helm install --wait` agotaria su tiempo "
            "sin explicar por que"
        )
        assert var in api, (
            f"{var} esta en el Secret pero el contenedor no lo lee: api.yaml nombra "
            "las claves una a una con secretKeyRef, asi que anadirla al Secret no basta"
        )


def test_el_readme_no_promete_una_cuenta_que_el_compose_no_crea():
    """La tabla de credenciales vale para el arranque local, no para el compose."""
    readme = _lee("README.md")
    assert readme, "no encuentro el README"
    inicio = readme.find("## Quick start")
    assert inicio != -1, "el README ya no tiene seccion de arranque rapido"
    arranque = readme[inicio:readme.find("\n## ", inicio + 5)]
    assert "demo account below" not in arranque, (
        "el arranque rapido manda entrar con la cuenta de la tabla de credenciales, "
        "y el compose corre en produccion: esa cuenta no se crea nunca por esa via"
    )
    assert "RACKMON_ADMIN_PASSWORD" in arranque, (
        "el arranque rapido no dice que hay que fijar RACKMON_ADMIN_PASSWORD, "
        "sin la cual `docker compose up` no levanta"
    )
