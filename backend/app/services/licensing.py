"""Qué funciones están disponibles. Desde la 1.3.0: todas, para todo el mundo.

RackMon nació como «núcleo abierto»: la monitorización era gratis y un puñado de
cosas —SSO, LDAP, la página de estado pública, los informes de SLA, la marca
blanca— pedían una licencia de pago, verificada aquí contra una clave Ed25519
embebida.

Ese modelo se retiró el 1 de noviembre de 2026, y conviene saber por qué: en
varios meses hubo **veintidós instalaciones y cero ventas**. No es que el precio
fuera alto; es que nadie llegó a tener el problema de pagar. Un producto que
nadie usa no se arregla cobrando menos, se arregla llegando a más gente. Así que
ahora hay **una sola edición con todo encendido**, sin claves, sin niveles y sin
asteriscos.

Este módulo sigue existiendo —en vez de borrarlo y tocar ocho ficheros más— con
una forma deliberadamente tonta: todo dice que sí. Se queda por tres razones
concretas:

  * `GET /api/v1/license` lo sigue sirviendo, y una instalación antigua que
    actualice no debe encontrarse un 500 en una pantalla que antes funcionaba;
  * quien ya tenga `RACKMON_LICENSE_KEY` puesto en su `.env` no tiene que ir a
    quitarlo: ahora simplemente da igual lo que valga;
  * si algún día volviera a haber algo de pago, el sitio donde ponerlo es este y
    no repartido por seis routers.

Lo que NO se ha conservado es la verificación criptográfica. Ya no hay nada que
verificar, y dejar código de firma que no decide nada es la clase de cosa que
alguien lee dentro de dos años y cree que sigue protegiendo algo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger("rackmon.license")

# Todo lo que el producto sabe hacer. Se mantienen los nombres de siempre porque
# la API los publica y hay instalaciones mirándolos.
FEATURE_SSO = "sso"
FEATURE_LDAP = "ldap"
FEATURE_WHITE_LABEL = "white_label"
FEATURE_SLA_REPORTS = "sla_reports"
FEATURE_STATUS_PAGE = "status_page"
FEATURE_MULTI_SITE = "multi_site"
FEATURE_HA_CLUSTERING = "ha_clustering"

ALL_FEATURES = frozenset({
    FEATURE_SSO,
    FEATURE_LDAP,
    FEATURE_WHITE_LABEL,
    FEATURE_SLA_REPORTS,
    FEATURE_STATUS_PAGE,
    FEATURE_MULTI_SITE,
    FEATURE_HA_CLUSTERING,
})

# Nombres antiguos, para que nada de fuera se rompa al actualizar. Ahora los tres
# valen lo mismo, que es todo.
PRO_FEATURES = ALL_FEATURES
ENTERPRISE_FEATURES = ALL_FEATURES


@dataclass(frozen=True)
class License:
    edition: str = "free"
    licensee: str = ""
    features: frozenset[str] = field(default_factory=lambda: ALL_FEATURES)
    expires_at: None = None          # nunca caduca: no hay nada que caducar
    max_devices: None = None         # sin tope de equipos
    valid: bool = True

    def has_feature(self, name: str) -> bool:
        return True


# La única licencia que existe. El nombre `COMMUNITY` se conserva porque lo
# importan las pruebas y algún módulo; ahora es simplemente «la edición», y lo
# trae todo.
FREE = License(edition="free", licensee="Free edition", features=ALL_FEATURES, valid=True)
COMMUNITY = FREE


def verify_license_key(key: str) -> License:
    """Antes verificaba una firma Ed25519. Ahora da igual lo que le pases.

    Se conserva la función porque hay instalaciones con `RACKMON_LICENSE_KEY` en
    su `.env` y no tienen por qué ir a quitarlo. Devuelve siempre la edición
    completa, incluso con la cadena vacía.
    """
    return FREE


def get_license() -> License:
    return FREE


def reload_license() -> License:
    return FREE


def has_feature(name: str) -> bool:
    """Todo está disponible. Siempre.

    Los seis puntos del código que antes llamaban aquí para cerrar una puerta ya
    no lo hacen: se quitaron al abrir el producto. Esta función se queda por si
    algún complemento de terceros la llamaba.
    """
    return True


def device_limit() -> None:
    """Sin tope. Antes una licencia podía fijar uno por bandas de precio."""
    return None
