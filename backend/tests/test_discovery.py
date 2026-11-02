"""Network discovery: range expansion, simulated scan, and import."""
from __future__ import annotations

from app.services import discovery


def test_expand_cidr_and_range_and_single():
    assert len(discovery.expand("10.0.0.0/28")) == 14  # .1 .. .14
    assert discovery.expand("192.168.1.10-12") == ["192.168.1.10", "192.168.1.11", "192.168.1.12"]
    assert discovery.expand("10.1.2.3") == ["10.1.2.3"]


def test_scan_simulator_finds_subset(client, operator_headers):
    r = client.post("/api/v1/discovery/scan", headers=operator_headers,
                    json={"target": "10.0.0.0/28"})
    assert r.status_code == 200
    found = r.json()
    ips = {h["ip"] for h in found}
    # Deterministic responders: last octet divisible by 3 (.3 .6 .9 .12).
    assert ips == {"10.0.0.3", "10.0.0.6", "10.0.0.9", "10.0.0.12"}
    assert all(h["sysname"] and not h["already_known"] for h in found)


def test_scan_flags_known(client, operator_headers):
    client.post("/api/v1/devices", headers=operator_headers,
                json={"name": "known", "ip": "10.0.0.6"})
    found = client.post("/api/v1/discovery/scan", headers=operator_headers,
                        json={"target": "10.0.0.0/28"}).json()
    known = {h["ip"]: h["already_known"] for h in found}
    assert known["10.0.0.6"] is True
    assert known["10.0.0.3"] is False


def test_import_creates_and_skips(client, operator_headers):
    client.post("/api/v1/devices", headers=operator_headers,
                json={"name": "existing", "ip": "10.0.0.9"})
    r = client.post("/api/v1/discovery/import", headers=operator_headers, json={
        "devices": [
            {"ip": "10.0.0.3", "name": "new-a"},
            {"ip": "10.0.0.9", "name": "dup"},
        ]
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["created"]) == 1
    assert body["skipped"] == ["10.0.0.9"]

    # Imported device is real and carries the default metric catalog.
    devs = client.get("/api/v1/devices", headers=operator_headers).json()
    new = next(d for d in devs if d["ip"] == "10.0.0.3")
    assert any(m["name"] == "temp_cpu" for m in new["metrics"])


def test_scan_invalid_target_400(client, operator_headers):
    r = client.post("/api/v1/discovery/scan", headers=operator_headers,
                    json={"target": "not-an-ip"})
    assert r.status_code == 400


def test_discovery_requires_operator(client, viewer_headers):
    assert client.post("/api/v1/discovery/scan", json={"target": "10.0.0.0/30"}).status_code == 401
    assert client.post("/api/v1/discovery/scan", headers=viewer_headers,
                       json={"target": "10.0.0.0/30"}).status_code == 403


# --- auditoría 14-oct: el escaneo real bloqueaba el servidor ----------------


def test_el_escaneo_real_no_prueba_las_direcciones_de_una_en_una(monkeypatch):
    """Cada dirección apagada se come el tiempo de espera entero.

    De una en una, una /24 con la mitad de las direcciones muertas tardaba más de
    cuatro minutos con un hilo del servidor ocupado todo el rato. Dos o tres
    escaneos a la vez —y escanear una red entera es la forma normal de usar
    esto— y la API dejaba de responder a todo lo demás.
    """
    import threading
    import time

    from app.config import get_settings
    from app.services import discovery

    monkeypatch.setattr(get_settings(), "poller_use_simulator", False, raising=False)
    a_la_vez = {"max": 0, "ahora": 0}
    cerrojo = threading.Lock()

    def _lento(ip, community, version):
        with cerrojo:
            a_la_vez["ahora"] += 1
            a_la_vez["max"] = max(a_la_vez["max"], a_la_vez["ahora"])
        time.sleep(0.05)
        with cerrojo:
            a_la_vez["ahora"] -= 1
        return {"sysname": ip, "vendor": None}

    monkeypatch.setattr(discovery, "_snmp_probe", _lento)
    t0 = time.monotonic()
    encontrados = discovery.scan("10.60.0.1-32")
    tardo = time.monotonic() - t0

    assert len(encontrados) == 32, "no puede perder equipos por hacerlo en paralelo"
    assert [h["ip"] for h in encontrados] == [f"10.60.0.{i}" for i in range(1, 33)], (
        "el orden de la red se altera y quien escanea no reconoce su propia red"
    )
    assert a_la_vez["max"] > 1, (
        "las direcciones se siguen probando de una en una: 512 equipos con el "
        "tiempo de espera por defecto son más de ocho minutos de hilo bloqueado"
    )
    assert tardo < 32 * 0.05 * 0.6, f"tardó {tardo:.2f}s, prácticamente en serie"


def test_una_direccion_que_falla_no_tumba_el_escaneo_entero(monkeypatch):
    from app.config import get_settings
    from app.services import discovery

    monkeypatch.setattr(get_settings(), "poller_use_simulator", False, raising=False)

    def _a_veces_revienta(ip, community, version):
        if ip.endswith(".3"):
            raise OSError("red inalcanzable")
        return {"sysname": ip, "vendor": None}

    monkeypatch.setattr(discovery, "_snmp_probe", _a_veces_revienta)
    encontrados = discovery.scan("10.61.0.1-5")
    assert [h["ip"] for h in encontrados] == [
        "10.61.0.1", "10.61.0.2", "10.61.0.4", "10.61.0.5"
    ]
