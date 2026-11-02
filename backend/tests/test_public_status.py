"""Pagina de estado publica: el interruptor del administrador y que no se escape nada.

Fue funcion de pago hasta la 1.3.0; ahora solo depende de que la enciendas."""
import json


def _enable(client, admin_headers, **cfg):
    body = {"enabled": True, **cfg}
    r = client.put("/api/v1/admin/settings/status_page", headers=admin_headers,
                   json={"value": body})
    assert r.status_code == 200, r.text


def test_hidden_until_enabled(client, admin_headers):
    # Apagada -> 404, y sin usar ninguna credencial.
    assert client.get("/api/v1/public/status").status_code == 404

    _enable(client, admin_headers, title="Acme Status")
    r = client.get("/api/v1/public/status")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Acme Status"
    assert body["overall"] in {"ok", "warning", "critical", "nodata"}
    assert set(body["summary"]) >= {"ok", "warning", "critical", "nodata", "maintenance"}
    assert isinstance(body["devices"], list)


def test_does_not_leak_secrets(client, admin_headers, sample_device):
    _enable(client, admin_headers)
    dump = json.dumps(client.get("/api/v1/public/status").json())
    # The sanitized board must never expose IPs, tags, or SNMP credentials.
    assert sample_device["ip"] not in dump          # 10.0.0.5
    assert "s3cret" not in dump                      # the SNMP community
    assert "compute" not in dump                     # a device tag


def test_la_pagina_publica_esta_disponible_sin_licencia(client, admin_headers):
    """Desde la 1.3.0 solo depende de que la enciendas tú, no de pagar."""
    _enable(client, admin_headers)
    assert client.get("/api/v1/public/status").status_code == 200


def test_apagada_sigue_dando_404(client):
    """Lo que sí sigue mandando es el interruptor del administrador."""
    assert client.get("/api/v1/public/status").status_code == 404


def test_temperatures_can_be_hidden(client, admin_headers):
    _enable(client, admin_headers, show_temperatures=False)
    body = client.get("/api/v1/public/status").json()
    assert all("temperature" not in d for d in body["devices"])
