"""Entrada directa a la demo pública, sin usuario ni contraseña.

Mucha gente abandona una demo solo por tener que teclear credenciales. Esto la
abre de par en par — pero SOLO en la demo del vendedor, y SOLO con una cuenta de
solo lectura. Estos tests existen para que no pueda degenerar en otra cosa.
"""
from __future__ import annotations

from app.config import get_settings


def _activar_demo(monkeypatch, email=""):
    s = get_settings()
    monkeypatch.setattr(s, "demo_mode", True, raising=False)
    monkeypatch.setattr(s, "demo_user_email", email, raising=False)


# --- apagado por defecto: ninguna instalación de cliente lo expone ----------


def test_demo_endpoint_is_invisible_by_default(client):
    """Lo más importante de todo: quien instala RackMon NO tiene esta puerta."""
    assert client.post("/api/v1/auth/demo").status_code == 404


def test_sso_config_reports_demo_off_by_default(client):
    assert client.get("/api/v1/auth/sso-config").json()["demo_mode"] is False


# --- encendido: funciona y entrega solo lectura -----------------------------


def test_demo_login_returns_a_working_session(client, monkeypatch):
    _activar_demo(monkeypatch)
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    yo = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert yo.status_code == 200
    assert yo.json()["role"] == "viewer", "la demo jamás puede entregar más que lectura"


def test_the_demo_session_cannot_change_anything(client, monkeypatch):
    """Un visitante anónimo no puede tocar los datos de la demo."""
    _activar_demo(monkeypatch)
    token = client.post("/api/v1/auth/demo").json()["access_token"]
    cab = {"Authorization": f"Bearer {token}"}

    creado = client.post("/api/v1/devices", headers=cab, json={
        "name": "intruso", "ip": "10.0.0.99", "snmp_version": "2c", "snmp_community": "x"})
    assert creado.status_code == 403, "la demo permitió crear un dispositivo"

    borrado = client.delete("/api/v1/devices/1", headers=cab)
    assert borrado.status_code == 403, "la demo permitió borrar un dispositivo"


def test_sso_config_announces_demo_when_on(client, monkeypatch):
    """La pantalla de login lo consulta para saber si debe entrar sola."""
    _activar_demo(monkeypatch)
    assert client.get("/api/v1/auth/sso-config").json()["demo_mode"] is True


# --- la salvaguarda: nunca una cuenta con permisos --------------------------


def test_it_refuses_to_hand_out_an_admin_account(client, monkeypatch):
    """Aunque alguien apunte la demo a una cuenta de administrador por error,
    esta puerta no reparte permisos: se niega."""
    _activar_demo(monkeypatch, email="admin@rackmon.io")
    r = client.post("/api/v1/auth/demo")
    assert r.status_code == 503, f"entregó una cuenta de admin ({r.status_code})"


def test_it_fails_cleanly_when_the_account_does_not_exist(client, monkeypatch):
    _activar_demo(monkeypatch, email="no-existe@rackmon.io")
    assert client.post("/api/v1/auth/demo").status_code == 503
