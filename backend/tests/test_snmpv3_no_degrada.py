"""SNMPv3 no puede degradarse a texto claro en silencio.

`build_usm` traducía el nombre del protocolo con un diccionario y un valor por
defecto:

    authProtocol=auth_map.get(cfg.get("auth_protocol", "none"), usmNoAuthProtocol)
    privProtocol=priv_map.get(cfg.get("priv_protocol", "none"), usmNoPrivProtocol)

Ante un nombre que no estuviera en el mapa —una errata tan corriente como
escribir "sha256" en minúsculas— la sesión salía **noAuthNoPriv**: sin firmar y
sin cifrar. El equipo seguía apareciendo configurado como authPriv en la
pantalla, el operador creía tener SNMPv3 seguro, y las credenciales viajaban en
claro por la red de gestión. Ni un aviso, ni una línea de log.

Los conjuntos AUTH_PROTOCOLS y PRIV_PROTOCOLS existían desde el principio en el
mismo fichero. No los miraba nadie.
"""
from __future__ import annotations

import pytest

from app.services import snmpv3

BUENA = {"security_name": "monitor", "auth_protocol": "SHA256", "auth_key": "clave-auth-1",
         "priv_protocol": "AES256", "priv_key": "clave-priv-1"}


def test_una_configuracion_correcta_sigue_valiendo():
    snmpv3.validar(BUENA)


@pytest.mark.parametrize("malo", ["sha256", "SHA-256", "SHA3", "hmac-sha2-256", "si"])
def test_una_errata_en_el_protocolo_de_autenticacion_se_rechaza(malo):
    cfg = dict(BUENA, auth_protocol=malo)
    with pytest.raises(ValueError, match="auth protocol"):
        snmpv3.validar(cfg)


@pytest.mark.parametrize("malo", ["aes256", "AES-256", "aes", "RC4"])
def test_una_errata_en_el_protocolo_de_cifrado_se_rechaza(malo):
    cfg = dict(BUENA, priv_protocol=malo)
    with pytest.raises(ValueError, match="privacy protocol"):
        snmpv3.validar(cfg)


def test_un_protocolo_sin_su_clave_se_rechaza():
    """Acaba en authKey=None, que para pysnmp es noAuth."""
    with pytest.raises(ValueError, match="auth_key"):
        snmpv3.validar(dict(BUENA, auth_key=""))
    with pytest.raises(ValueError, match="priv_key"):
        snmpv3.validar(dict(BUENA, priv_key=""))


def test_cifrar_sin_autenticar_no_existe():
    """RFC 3414: no hay privNoAuth. pysnmp lo aceptaba y caía en noAuthNoPriv."""
    with pytest.raises(ValueError):
        snmpv3.validar({"security_name": "u", "priv_protocol": "AES", "priv_key": "k" * 8})


def test_noauthnopriv_explicito_si_se_permite():
    """Quien lo pide a sabiendas puede tenerlo; lo que no vale es acabar ahí sin
    quererlo."""
    snmpv3.validar({"security_name": "lectura"})
    snmpv3.validar({"security_name": "lectura", "auth_protocol": "none",
                    "priv_protocol": "none"})


def test_el_api_rechaza_la_errata_en_vez_de_guardarla(client, operator_headers):
    r = client.post("/api/v1/devices", headers=operator_headers, json={
        "name": "v3-con-errata", "ip": "10.73.0.1", "snmp_version": "3",
        "snmpv3": {"security_name": "monitor", "auth_protocol": "sha256",
                   "auth_key": "clave-auth-1", "priv_protocol": "AES", "priv_key": "clave-priv-1"},
    })
    assert r.status_code == 400, (
        f"se ha guardado un equipo con un protocolo inexistente ({r.status_code}): "
        "la pantalla dirá authPriv y el tráfico irá en claro"
    )


def test_el_api_sigue_aceptando_una_buena(client, operator_headers):
    r = client.post("/api/v1/devices", headers=operator_headers, json={
        "name": "v3-correcto", "ip": "10.73.0.2", "snmp_version": "3", "snmpv3": BUENA,
    })
    assert r.status_code == 201, r.text
    assert r.json()["has_snmpv3"] is True
