"""El formulario de soporte no existe en la demo pública.

En la demo entra cualquiera sin cuenta, así que ese formulario no es "un usuario
contactando con su proveedor": es un buzón abierto a internet con la dirección
del vendedor al otro lado. Se apaga en el SERVIDOR, no escondiendo el botón:
esconderlo en la interfaz no impide que alguien llame al endpoint.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture()
def en_demo(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "demo_mode", True, raising=False)
    monkeypatch.setattr(s, "support_url", "https://rackmon.app/support/messages", raising=False)
    return s


def test_la_demo_dice_que_no_hay_canal_de_soporte(client: TestClient, viewer_headers: dict, en_demo):
    r = client.get("/api/v1/support/config", headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is False, (
        "la demo ofrece el formulario de soporte; el widget se dibujaría"
    )


def test_la_demo_rechaza_el_envio_aunque_llamen_al_endpoint(
    client: TestClient, viewer_headers: dict, en_demo
):
    r = client.post(
        "/api/v1/support",
        headers=viewer_headers,
        json={"message": "hola desde la demo", "kind": "question"},
    )
    assert r.status_code == 503, "la demo ha aceptado reenviar un mensaje al vendedor"


def test_una_instalacion_normal_sigue_teniendo_soporte(
    client: TestClient, viewer_headers: dict, monkeypatch
):
    s = get_settings()
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    monkeypatch.setattr(s, "support_url", "https://rackmon.app/support/messages", raising=False)
    r = client.get("/api/v1/support/config", headers=viewer_headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True


def test_sin_buzon_configurado_tampoco_hay_soporte(
    client: TestClient, viewer_headers: dict, monkeypatch
):
    s = get_settings()
    monkeypatch.setattr(s, "demo_mode", False, raising=False)
    monkeypatch.setattr(s, "support_url", "", raising=False)
    r = client.get("/api/v1/support/config", headers=viewer_headers)
    assert r.json()["enabled"] is False
