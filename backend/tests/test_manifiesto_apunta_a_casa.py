"""El aviso a las instalaciones tiene que llegar a alguna parte.

Hasta la 1.2.10, la direccion por defecto del manifiesto era
`https://rackmon.io/updates/manifest.json`. El dominio del fabricante es
rackmon.APP: rackmon.io no es nuestro y ni siquiera resuelve. Y nada lo
sobreescribia —ni el .env.example, ni docker-compose, ni la documentacion—, asi
que una instalacion que encendiera la comprobacion de actualizaciones preguntaba
a un dominio inexistente y no recibia nada.

Importa mas de lo que parece: el manifiesto es el UNICO canal para decirle a
quien ya tiene RackMon instalado que hay algo que arreglar. Con esto roto, un
aviso de seguridad se publica y no lo lee nadie.

Y hay un segundo motivo: rackmon.io esta libre. Quien lo registre le sirve un
manifiesto a toda instalacion que siga con el valor por defecto, y los anuncios
se pintan con su titulo y su enlace dentro del panel.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from app.services import updates

DOMINIO = "rackmon.app"

# Solo URL. Los correos de ejemplo (admin@rackmon.io) son otra cosa: son el valor
# por defecto de una cuenta sembrada y cambiarlos crearia un segundo
# administrador en toda instalacion que no los haya tocado.
URL_AJENA = re.compile(r"https?://[a-z0-9.-]*rackmon\.io")


def test_la_direccion_por_defecto_es_la_nuestra():
    host = urlparse(updates.DEFAULT_MANIFEST_URL).hostname or ""
    assert host == DOMINIO, (
        f"el manifiesto por defecto apunta a {host!r}, que no es nuestro dominio: "
        "ninguna instalacion recibiria un aviso de seguridad"
    )


def test_se_pide_por_https():
    assert updates.DEFAULT_MANIFEST_URL.startswith("https://")


def test_ningun_sitio_del_proyecto_apunta_ya_al_dominio_equivocado():
    """La red: que no vuelva por otro fichero.

    Antes esto solo recorria `backend/app`, y por ese hueco se colaba
    `scripts/release.py` — la herramienta que ESCRIBE el manifiesto — con
    `https://rackmon.io/download` como valor por defecto de `--url`. Una release
    cortada sin pasar `--url` habria escrito el dominio equivocado en el fichero
    que leen las instalaciones, deshaciendo el arreglo de la 1.2.10 sin que nadie
    tocara `updates.py`. Asi que se recorre el proyecto entero.
    """
    raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    SALTAR = {".venv", "node_modules", "dist", "__pycache__", ".git", "build",
              "licensing_server", "coverage", "website"}
    EXTENSIONES = (".py", ".ts", ".tsx", ".yml", ".yaml", ".json", ".md",
                   ".sh", ".example", ".toml")
    yo = os.path.basename(__file__)

    culpables = []
    for base, dirs, ficheros in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in SALTAR]
        for n in ficheros:
            if not n.endswith(EXTENSIONES) or n == yo:
                continue
            ruta = os.path.join(base, n)
            try:
                with open(ruta, encoding="utf-8", errors="ignore") as fh:
                    texto = fh.read()
            except OSError:
                continue
            for m in URL_AJENA.finditer(texto):
                culpables.append(f"{os.path.relpath(ruta, raiz)}: {m.group(0)}")

    assert not culpables, (
        "siguen apuntando a un dominio que no es nuestro:\n  " + "\n  ".join(culpables)
    )
