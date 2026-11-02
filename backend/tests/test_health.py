from fastapi.testclient import TestClient


def test_health_ok(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert "uptime_seconds" in body


def test_prometheus_metrics_requires_auth(client: TestClient):
    # /metrics must never be exposed unauthenticated.
    assert client.get("/metrics").status_code == 401


def test_prometheus_metrics_with_user_auth(client: TestClient, admin_headers: dict):
    r = client.get("/metrics", headers=admin_headers)
    assert r.status_code == 200
    assert "rackmon_polls_total" in r.text or "rackmon_devices_total" in r.text


def test_prometheus_metrics_with_metrics_token(client: TestClient, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_token", "scrape-token-123")
    assert client.get("/metrics").status_code == 401  # no token supplied
    r = client.get("/metrics", headers={"Authorization": "Bearer scrape-token-123"})
    assert r.status_code == 200


def test_openapi_is_not_served_unless_it_is_turned_on(client: TestClient):
    """Este test decia `status_code == 200` y no comprobaba absolutamente nada.

    La SPA responde 200 a CUALQUIER ruta que no reconoce, asi que pasaba igual
    con la documentacion abierta, cerrada o inexistente. Lo que hay que mirar
    es el CONTENIDO: si vuelve un documento OpenAPI de verdad.
    """
    r = client.get("/openapi.json")
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = None
    assert not (isinstance(cuerpo, dict) and "openapi" in cuerpo), (
        "se esta sirviendo la referencia de la API sin haberla activado"
    )


def test_docs_can_be_turned_on_on_purpose():
    """Y cuando se encienden a proposito, tienen que estar."""
    import os
    import subprocess
    import sys

    entorno = {**os.environ, "RACKMON_API_DOCS_ENABLED": "true"}
    r = subprocess.run(
        [sys.executable, "-c",
         "import app.main as m;print(m.app.docs_url, m.app.redoc_url, m.app.openapi_url)"],
        capture_output=True, text=True, env=entorno,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["/docs", "/redoc", "/openapi.json"], r.stdout


def test_login_unknown_email_runs_verify(client: TestClient, monkeypatch):
    """Anti-enumeration: an unknown email must still pay the password-hash cost
    so response timing does not reveal which accounts exist."""
    import app.routers.auth as auth_mod

    calls = []
    orig = auth_mod.verify_password
    monkeypatch.setattr(auth_mod, "verify_password", lambda pw, h: calls.append(1) or orig(pw, h))
    r = client.post("/api/v1/auth/login", json={"email": "ghost-nobody@example.com", "password": "x"})
    assert r.status_code == 401
    assert calls, "verify_password must run even for an unknown email"


def test_security_headers(client: TestClient):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
    # Un panel de monitorización no usa cámara, micro ni ubicación: negarlas
    # explícitamente limita el daño si alguna vez se cuela un script.
    permisos = r.headers.get("Permissions-Policy", "")
    for capacidad in ("camera=()", "microphone=()", "geolocation=()"):
        assert capacidad in permisos, f"falta {capacidad} en Permissions-Policy"


def test_root_placeholder_when_no_frontend(client: TestClient):
    # In the test image the frontend is not built, so root returns API info.
    r = client.get("/")
    assert r.status_code == 200


def test_api_docs_are_closed_in_production():
    """La documentación interactiva no puede quedar abierta en una instalación
    real: sin autenticar, entrega el mapa completo de la API (rutas, parámetros
    y esquemas). En desarrollo y en los tests sí está, que es donde sirve.

    Se comprueba en un proceso aparte: recargar app.main a mitad de la suite
    dejaría el estado de los demás tests tocado.
    """
    import os
    import subprocess
    import sys

    entorno = {
        **os.environ,
        "RACKMON_ENVIRONMENT": "production",
        # secretos válidos, o el guardián de arranque se niega a levantar
        "RACKMON_JWT_SECRET": "x" * 48,
        "RACKMON_MASTER_KEY": "y" * 48,
        "RACKMON_ADMIN_PASSWORD": "z" * 24,
    }
    r = subprocess.run(
        [sys.executable, "-c",
         "import app.main as m;print(m.settings.environment, m.app.docs_url, "
         "m.app.redoc_url, m.app.openapi_url)"],
        capture_output=True, text=True, env=entorno,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["production", "None", "None", "None"], (
        "la documentación sigue abierta en producción: " + r.stdout
    )
