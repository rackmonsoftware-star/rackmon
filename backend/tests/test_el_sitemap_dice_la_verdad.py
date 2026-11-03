"""El sitemap es lo que los buscadores leen para decidir si vuelven.

Se mantenia a mano, y se noto: el 3-nov-2026 se reescribieron las 19 paginas del
sitio y el sitemap seguia diciendo que ninguna se habia tocado desde el 13 de
octubre. Google usa `<lastmod>` justo para eso, asi que el dia que mas interesaba
que volviera a rastrear, el sitio le estaba diciendo que no hacia falta.

Ahora las fechas las pone `publicar-web.sh`, y solo a las paginas que de verdad
cambian en esa pasada. Estas pruebas vigilan lo que ese automatismo no puede:
que el sitemap y las paginas que hay en disco sigan hablando de lo mismo.

La regla es la pagina, no una lista escrita aparte: una pagina entra en el
sitemap salvo que ella misma se declare `noindex`. Asi no hay dos listas que
puedan separarse, que es como se pierden las paginas nuevas.
"""
from __future__ import annotations

import datetime as dt
import os
import re

import pytest

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
WEB = os.path.join(RAIZ, "website")
SITEMAP = os.path.join(WEB, "sitemap.xml")
BASE = "https://rackmon.app/"

# `website/` esta en el .gitignore a proposito: ahi vive la clave de IndexNow y
# no puede acabar publicada. En un clon del repositorio publico no hay sitio que
# comprobar, asi que estas pruebas solo corren desde la maquina que publica.
# Para que el salto no sea un agujero, `publicar-web.sh` las ejecuta antes de
# subir nada: es el momento en que de verdad importan.
if not os.path.isfile(SITEMAP):
    pytest.skip(
        "website/ no esta en el repositorio publico (lleva la clave de IndexNow); "
        "el sitemap se comprueba al publicar, desde publicar-web.sh",
        allow_module_level=True,
    )


def _texto(ruta: str) -> str:
    with open(ruta, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _sitemap() -> str:
    return _texto(SITEMAP)


def _entradas() -> list[tuple[str, str]]:
    """[(loc, lastmod)] en el orden del fichero."""
    bloques = re.findall(r"<url>(.*?)</url>", _sitemap(), re.S)
    salida = []
    for b in bloques:
        loc = re.search(r"<loc>([^<]*)</loc>", b)
        mod = re.search(r"<lastmod>([^<]*)</lastmod>", b)
        salida.append((loc.group(1).strip() if loc else "", mod.group(1).strip() if mod else ""))
    return salida


def _paginas_en_disco() -> list[str]:
    salida = []
    for base, _, nombres in os.walk(WEB):
        for n in nombres:
            if n.endswith(".html"):
                salida.append(os.path.relpath(os.path.join(base, n), WEB).replace(os.sep, "/"))
    return sorted(salida)


def _url_de(pagina: str) -> str:
    return BASE if pagina == "index.html" else BASE + pagina


def test_toda_pagina_indexable_esta_en_el_sitemap():
    listadas = {loc for loc, _ in _entradas()}
    faltan = [
        p
        for p in _paginas_en_disco()
        if "noindex" not in _texto(os.path.join(WEB, p)).lower() and _url_de(p) not in listadas
    ]
    assert not faltan, (
        "estas paginas se publican pero no estan en el sitemap, asi que nadie las "
        f"buscara: {faltan}. Si alguna no debe indexarse, que lo diga ella con "
        "<meta name='robots' content='noindex'>."
    )


def test_el_sitemap_no_anuncia_paginas_que_no_existen():
    huerfanas = []
    for loc, _ in _entradas():
        if not loc.startswith(BASE):
            huerfanas.append(f"{loc} (no es nuestro dominio)")
            continue
        resto = loc[len(BASE) :] or "index.html"
        if not os.path.isfile(os.path.join(WEB, resto)):
            huerfanas.append(loc)
    assert not huerfanas, (
        f"el sitemap manda a los buscadores a paginas que no estan: {huerfanas}"
    )


def test_el_sitemap_no_contradice_a_la_propia_pagina():
    contradictorias = []
    for loc, _ in _entradas():
        resto = loc[len(BASE) :] if loc.startswith(BASE) else ""
        ruta = os.path.join(WEB, resto or "index.html")
        if os.path.isfile(ruta) and "noindex" in _texto(ruta).lower():
            contradictorias.append(loc)
    assert not contradictorias, (
        "el sitemap pide que se indexen paginas que se declaran noindex: "
        f"{contradictorias}. Una de las dos cosas esta mal."
    )


def test_ninguna_fecha_esta_en_el_futuro_ni_falta():
    hoy = dt.date.today()
    problemas = []
    for loc, mod in _entradas():
        if not mod:
            problemas.append(f"{loc}: sin <lastmod>")
            continue
        try:
            fecha = dt.date.fromisoformat(mod)
        except ValueError:
            problemas.append(f"{loc}: fecha ilegible {mod!r}")
            continue
        if fecha > hoy:
            problemas.append(f"{loc}: fechada en el futuro ({mod})")
    assert not problemas, (
        "fechas del sitemap que un buscador no se puede creer:\n  "
        + "\n  ".join(problemas)
    )


def test_cada_entrada_trae_loc_y_una_sola_fecha():
    crudo = _sitemap()
    assert crudo.count("<url>") == crudo.count("</url>"), "hay un bloque <url> sin cerrar"
    assert crudo.count("<loc>") == crudo.count("<lastmod>"), (
        f"{crudo.count('<loc>')} direcciones y {crudo.count('<lastmod>')} fechas: "
        "publicar-web.sh empareja cada fecha con el <loc> que tiene encima, asi que "
        "si no van de uno en uno refechara la pagina equivocada."
    )
