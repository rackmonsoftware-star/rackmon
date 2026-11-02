"""Con qué métricas arranca un equipo creado sin especificarlas.

Hasta la 1.2.3 eran OID de Cisco para todo el mundo — y no solo al crear un
equipo a mano, sino también al importar desde el descubrimiento de red, que es la
vía masiva. Alguien escaneaba su subred, importaba cuarenta equipos de cinco
marcas, y los cuarenta se llevaban el catálogo de un switch Cisco. En cualquier
cosa que no fuera Cisco eso devuelve "no hay datos" sin un solo error visible: el
equipo aparece creado, enchufado y mudo.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.templates import TEMPLATES, catalogo_por_defecto, plantilla_para

CISCO = "1.3.6.1.4.1.9."


@pytest.mark.parametrize(
    "vendor,esperada",
    [
        ("Dell", "dell-idrac"),
        ("dell", "dell-idrac"),
        ("Dell Inc. PowerEdge R750", "dell-idrac"),
        ("iDRAC9", "dell-idrac"),
        ("HPE", "hpe-ilo"),
        ("Hewlett Packard Enterprise", "hpe-ilo"),
        ("ProLiant DL380", "hpe-ilo"),
        ("APC", "apc-pdu"),
        ("Schneider Electric", "apc-pdu"),
    ],
)
def test_cada_fabricante_conocido_recibe_su_plantilla(vendor, esperada):
    assert plantilla_para(vendor) == esperada


@pytest.mark.parametrize(
    "vendor",
    ["", None, "   ", "Supermicro", "Synology", "Juniper", "Cisco", "HP LaserJet", "lo-que-sea"],
)
def test_lo_desconocido_recibe_la_neutral_no_la_de_cisco(vendor):
    """Ante la duda, el estándar abierto, no la rama privada de una empresa."""
    assert plantilla_para(vendor) == "generic-server"


def test_hp_a_secas_no_se_confunde_con_hpe():
    """Hay impresoras HP y switches HP ProCurve; el catálogo de iLO no les sirve."""
    assert plantilla_para("HP LaserJet 4200") == "generic-server"
    assert plantilla_para("HP ProCurve 2920") == "generic-server"


def test_el_catalogo_por_defecto_no_lleva_oid_de_cisco():
    for vendor in (None, "", "Supermicro", "Dell", "HPE", "APC"):
        for _n, _l, _u, oid, _e, _i in catalogo_por_defecto(vendor):
            assert not oid.startswith(CISCO), (
                f"a un equipo {vendor!r} se le está poniendo un OID de Cisco: {oid}"
            )


def test_el_catalogo_trae_siempre_una_temperatura_de_entrada():
    """Es la métrica que representa al equipo en el panel desde la 1.2.2."""
    for vendor in (None, "Dell", "HPE", "APC", "Supermicro"):
        nombres = [m[0] for m in catalogo_por_defecto(vendor)]
        assert "temp_inlet" in nombres, f"{vendor!r} arranca sin sensor de entrada"


def test_las_escalas_vienen_de_la_plantilla():
    """Dell devuelve décimas de grado: sin escala, 27,5 °C se guarda como 275."""
    dell = {m[0]: m[4] for m in catalogo_por_defecto("Dell")}
    assert dell["temp_inlet"] == 0.1
    apc = {m[0]: m[4] for m in catalogo_por_defecto("APC")}
    assert apc["temp_inlet"] == 0.1
    hpe = {m[0]: m[4] for m in catalogo_por_defecto("HPE")}
    assert hpe["temp_inlet"] == 1.0


def test_todas_las_plantillas_devuelven_tuplas_de_seis():
    for nombre, t in TEMPLATES.items():
        for m in t["metrics"]:
            assert len(m) == 6, f"{nombre}: {m!r} no tiene 6 campos"


# --------------------------------------------------------------------------
# De punta a punta, por la API
# --------------------------------------------------------------------------
def test_crear_un_dell_sin_metricas_le_da_las_de_dell(client: TestClient, admin_headers: dict):
    r = client.post(
        "/api/v1/devices",
        headers=admin_headers,
        json={"name": "pe-r750", "ip": "10.60.0.1", "vendor": "Dell", "community": "public"},
    )
    assert r.status_code == 201, r.text
    metricas = {m["name"]: m for m in r.json()["metrics"]}
    assert "temp_inlet" in metricas
    assert metricas["temp_inlet"]["oid"].startswith("1.3.6.1.4.1.674.")
    assert not metricas["temp_inlet"]["oid"].startswith(CISCO)


def test_crear_un_equipo_de_marca_desconocida_no_le_da_oid_de_cisco(
    client: TestClient, admin_headers: dict
):
    r = client.post(
        "/api/v1/devices",
        headers=admin_headers,
        json={"name": "raro-01", "ip": "10.60.0.2", "vendor": "Supermicro", "community": "public"},
    )
    assert r.status_code == 201, r.text
    for m in r.json()["metrics"]:
        assert not m["oid"].startswith(CISCO), f"{m['name']} se llevó un OID de Cisco"


def test_el_descubrimiento_conserva_el_fabricante_que_ya_habia_detectado(
    client: TestClient, admin_headers: dict
):
    """El escaneo deduce el fabricante del sysDescr y lo devuelve; antes se perdía
    al importar, así que el equipo se creaba sin fabricante y con el catálogo
    equivocado."""
    r = client.post(
        "/api/v1/discovery/import",
        headers=admin_headers,
        json={"devices": [{"ip": "10.61.0.1", "name": "hpe-01", "vendor": "HPE ProLiant"}]},
    )
    assert r.status_code == 200, r.text
    creados = r.json()["created"]
    assert len(creados) == 1

    d = client.get(f"/api/v1/devices/{creados[0]}", headers=admin_headers).json()
    assert d["vendor"] == "HPE ProLiant", "el fabricante detectado se ha perdido"
    metricas = {m["name"]: m for m in d["metrics"]}
    assert metricas["temp_inlet"]["oid"].startswith("1.3.6.1.4.1.232."), (
        "un HPE importado no recibió el catálogo de HPE"
    )


# --------------------------------------------------------------------------
# Emparejar por subcadena se tragaba cosas que no son servidores
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vendor",
    [
        "Hewlett-Packard HP LaserJet 4200",
        "HP OfficeJet Pro 9010",
        "Hewlett Packard ProCurve 2920",
        "HPE Aruba 6300M",
        "Dell Networking N2048",
        "Dell PowerConnect 2824",
        "Dell Force10 S4810",
        "HPE MSA 2060",
    ],
)
def test_lo_que_no_es_un_servidor_no_recibe_catalogo_de_servidor(vendor):
    """'Hewlett-Packard HP LaserJet' contiene 'hewlett' y se llevaba el catálogo
    de iLO: SNMP respondía 'No Such Instance' y la impresora quedaba creada,
    habilitada y muda, sin un error en pantalla."""
    assert plantilla_para(vendor) == "generic-server", (
        f"{vendor!r} ha recibido un catálogo que no le corresponde"
    )


@pytest.mark.parametrize(
    "vendor,esperada",
    [
        ("Dell Inc. PowerEdge R750", "dell-idrac"),
        ("iDRAC9 Enterprise", "dell-idrac"),
        ("HPE ProLiant DL380 Gen10", "hpe-ilo"),
        ("Integrated Lights-Out 5 (iLO 5)", "hpe-ilo"),
        ("APC rPDU2 AP8959", "apc-pdu"),
        ("APC NetBotz 250", "apc-pdu"),
    ],
)
def test_las_senales_fuertes_siguen_funcionando(vendor, esperada):
    """Nombrar el producto manda sobre cualquier otra cosa del texto."""
    assert plantilla_para(vendor) == esperada


def test_el_nombre_de_la_empresa_a_secas_sigue_valiendo():
    """Un 'Dell' pelado en un rack es casi siempre un PowerEdge. Vale mientras
    nada en el texto lo desmienta."""
    assert plantilla_para("Dell") == "dell-idrac"
    assert plantilla_para("Dell Inc.") == "dell-idrac"
    assert plantilla_para("APC") == "apc-pdu"
