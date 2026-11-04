"""La versión tiene que decir lo mismo en los cinco sitios donde está escrita.

No es un detalle de orden. El chart de Helm llevaba `appVersion: 1.0.0-mvp` y
`image.tag: "1.0.0"` cuando el producto iba por la 1.2.10: cualquiera que hiciera
`helm install` desde el repositorio se instalaba una imagen de dos versiones
atrás —sin el arreglo de la lectura de ficheros sin cuenta— y no se enteraba,
porque el despliegue funcionaba.

`APP_VERSION` en config.py manda. El resto tiene que seguirle:

  * `deploy/helm/rackmon/Chart.yaml`  -> appVersion (qué versión despliega)
  * `deploy/helm/rackmon/values.yaml` -> image.tag  (qué imagen baja)
  * `website/updates/manifest.json`   -> stable.version (qué anuncia a las
    instalaciones; vive fuera del repositorio público, así que se comprueba solo
    si está presente)
  * `frontend/package.json`           -> version

`scripts/release.py` los deja cuadrados; esta prueba es la red por si alguien
edita uno a mano.
"""
from __future__ import annotations

import json
import os
import re

import pytest

from app.config import APP_VERSION

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _lee(*partes: str) -> str | None:
    ruta = os.path.join(RAIZ, *partes)
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()


def test_la_version_es_un_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", APP_VERSION), APP_VERSION


def test_el_chart_despliega_esta_version():
    texto = _lee("deploy", "helm", "rackmon", "Chart.yaml")
    assert texto, "no encuentro el Chart.yaml"
    m = re.search(r'^appVersion:\s*"?([^"\s]+)"?\s*$', texto, re.M)
    assert m, "el Chart.yaml no declara appVersion"
    assert m.group(1) == APP_VERSION, (
        f"el chart despliega {m.group(1)!r} y el producto va por {APP_VERSION!r}"
    )


def test_el_chart_baja_la_imagen_de_esta_version():
    texto = _lee("deploy", "helm", "rackmon", "values.yaml")
    assert texto, "no encuentro el values.yaml"
    m = re.search(r'^\s+tag:\s*"?([^"\s]+)"?\s*$', texto, re.M)
    assert m, "el values.yaml no fija image.tag"
    assert m.group(1) == APP_VERSION, (
        f"el chart baja la imagen {m.group(1)!r} y el producto va por {APP_VERSION!r}: "
        "quien instale por Helm se lleva una version distinta de la que cree"
    )


def test_el_frontend_declara_la_misma_version():
    texto = _lee("frontend", "package.json")
    assert texto, "no encuentro el package.json"
    assert json.loads(texto)["version"] == APP_VERSION


def test_el_manifiesto_anuncia_esta_version():
    """Solo si el manifiesto esta presente: vive con el sitio, que no se publica.

    Desde el 4-nov-2026 el sitio esta FUERA de este repositorio (lleva la clave
    de IndexNow, que no puede acabar publicada), asi que el manifiesto se busca
    tambien al lado, en `cloudflare/web/`. Sin esta segunda ruta la prueba se
    saltaba en silencio tras la mudanza y dejaba de vigilar lo que vigilaba:
    que el aviso que leen las instalaciones anuncie la version que de verdad hay.
    """
    texto = _lee("website", "updates", "manifest.json")
    if texto is None:
        fuera = os.path.join(
            os.path.dirname(RAIZ), "cloudflare", "web", "updates", "manifest.json"
        )
        if os.path.isfile(fuera):
            with open(fuera, encoding="utf-8") as fh:
                texto = fh.read()
    if texto is None:
        pytest.skip("el manifiesto no esta ni en este arbol ni en cloudflare/web/")
    datos = json.loads(texto)
    assert datos["stable"]["version"] == APP_VERSION, (
        f"el manifiesto anuncia {datos['stable']['version']!r} y el producto va por "
        f"{APP_VERSION!r}: las instalaciones verian el aviso equivocado"
    )
