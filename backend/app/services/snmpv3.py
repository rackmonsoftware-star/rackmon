"""SNMPv3 credentials (Fase 2).

Credentials are stored as an encrypted JSON blob on the device (never returned
by the API). ``encode``/``decode`` and ``build_usm`` are unit-tested;
``build_usm`` constructs a pysnmp USM user object but performs no network I/O.
"""
from __future__ import annotations

import json

from ..crypto import decrypt, encrypt

# Human names -> pysnmp protocol objects (imported lazily in build_usm).
AUTH_PROTOCOLS = {"none", "MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"}
PRIV_PROTOCOLS = {"none", "DES", "3DES", "AES", "AES192", "AES256"}
SECURITY_LEVELS = {"noAuthNoPriv", "authNoPriv", "authPriv"}


def encode(cfg: dict) -> str:
    """Encrypt a v3 credential dict to an at-rest blob."""
    return encrypt(json.dumps(cfg, separators=(",", ":")))


def decode(blob: str | None) -> dict | None:
    if not blob:
        return None
    raw = decrypt(blob)
    return json.loads(raw) if raw else None


def security_level(cfg: dict) -> str:
    auth = cfg.get("auth_protocol", "none") not in (None, "", "none")
    priv = cfg.get("priv_protocol", "none") not in (None, "", "none")
    if auth and priv:
        return "authPriv"
    if auth:
        return "authNoPriv"
    return "noAuthNoPriv"


def _normaliza(valor) -> str:
    """"", None y "none" significan lo mismo: sin protocolo."""
    v = (valor or "none").strip()
    return "none" if v.lower() == "none" or v == "" else v


def validar(cfg: dict) -> None:
    """Rechaza una configuración v3 que no se pueda aplicar TAL COMO SE ESCRIBIÓ.

    Antes esto no existía y los dos diccionarios de abajo se consultaban con
    `.get(nombre, usmNoAuthProtocol)`. Es decir: ante un nombre que no estuviera
    en el mapa —una errata como "sha256" en minúsculas, un "SHA-256" con guion,
    o un protocolo que no soportamos— la sesión salía **sin autenticación y sin
    cifrado**. El equipo quedaba configurado como authPriv en la pantalla, el
    operador creía tener SNMPv3 seguro, y las credenciales viajaban en claro por
    la red sin una sola línea que lo dijera. Degradar en silencio un control de
    seguridad que alguien ha pedido expresamente es peor que no ofrecerlo.

    Lo mismo con las claves: un protocolo de autenticación sin su clave acaba en
    pysnmp como authKey=None, que otra vez es noAuth. Si se pide, hace falta.
    """
    if not (cfg.get("security_name") or "").strip():
        raise ValueError("SNMPv3 requires a security_name (the USM user)")

    auth = _normaliza(cfg.get("auth_protocol"))
    priv = _normaliza(cfg.get("priv_protocol"))

    if auth not in AUTH_PROTOCOLS:
        raise ValueError(
            f"unknown SNMPv3 auth protocol {auth!r}; use one of "
            f"{', '.join(sorted(AUTH_PROTOCOLS))}"
        )
    if priv not in PRIV_PROTOCOLS:
        raise ValueError(
            f"unknown SNMPv3 privacy protocol {priv!r}; use one of "
            f"{', '.join(sorted(PRIV_PROTOCOLS))}"
        )
    if auth != "none" and not (cfg.get("auth_key") or "").strip():
        raise ValueError(f"auth protocol {auth} is set but auth_key is empty")
    if priv != "none" and not (cfg.get("priv_key") or "").strip():
        raise ValueError(f"privacy protocol {priv} is set but priv_key is empty")
    if priv != "none" and auth == "none":
        # Lo prohíbe la propia RFC 3414: no hay authNoPriv al revés. pysnmp lo
        # aceptaría y acabaría en noAuthNoPriv, otra vez en silencio.
        raise ValueError("SNMPv3 privacy requires authentication (there is no privNoAuth)")


def build_usm(cfg: dict):  # returns pysnmp UsmUserData
    """Construct a pysnmp USM user from a credential dict. No network I/O."""
    validar(cfg)
    from pysnmp.hlapi.asyncio import (
        UsmUserData, usmDESPrivProtocol, usmAesCfb128Protocol, usmAesCfb192Protocol,
        usmAesCfb256Protocol, usmHMACMD5AuthProtocol, usmHMACSHAAuthProtocol,
        usmHMAC128SHA224AuthProtocol, usmHMAC192SHA256AuthProtocol,
        usmHMAC256SHA384AuthProtocol, usmHMAC384SHA512AuthProtocol,
        usm3DESEDEPrivProtocol, usmNoAuthProtocol, usmNoPrivProtocol,
    )

    auth_map = {
        "none": usmNoAuthProtocol, "MD5": usmHMACMD5AuthProtocol,
        "SHA": usmHMACSHAAuthProtocol, "SHA224": usmHMAC128SHA224AuthProtocol,
        "SHA256": usmHMAC192SHA256AuthProtocol, "SHA384": usmHMAC256SHA384AuthProtocol,
        "SHA512": usmHMAC384SHA512AuthProtocol,
    }
    priv_map = {
        "none": usmNoPrivProtocol, "DES": usmDESPrivProtocol, "3DES": usm3DESEDEPrivProtocol,
        "AES": usmAesCfb128Protocol, "AES192": usmAesCfb192Protocol, "AES256": usmAesCfb256Protocol,
    }
    # Sin valor por defecto en el .get: `validar()` ya ha garantizado que el
    # nombre está en el mapa, y un KeyError ruidoso es infinitamente preferible
    # a una sesión degradada a texto claro que nadie llega a ver.
    return UsmUserData(
        cfg["security_name"],
        authKey=cfg.get("auth_key") or None,
        privKey=cfg.get("priv_key") or None,
        authProtocol=auth_map[_normaliza(cfg.get("auth_protocol"))],
        privProtocol=priv_map[_normaliza(cfg.get("priv_protocol"))],
    )
