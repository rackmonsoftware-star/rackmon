"""HEAD tiene que funcionar donde alguien vaya a apuntar un monitor.

RackMon devolvía 405 a CUALQUIER petición HEAD, incluida la de `/health`. FastAPI,
a diferencia de Starlette, no añade HEAD por declarar un GET.

Por qué importa en un producto de monitorización: Uptime Kuma, UptimeRobot,
Pingdom, los `check_http` de Nagios y buena parte de los balanceadores usan HEAD
por defecto. El cliente apuntaba su monitor al `/health` de RackMon y veía
"caído" de forma permanente con el servicio perfectamente sano.

Una petición HEAD devuelve las mismas cabeceras que la GET y el cuerpo vacío; eso
lo hace Starlette por su cuenta. Aquí solo se comprueba que el método esté
PERMITIDO y que diga la verdad sobre el estado.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("ruta", ["/health", "/api/v1/health"])
def test_head_a_health_no_devuelve_405(client: TestClient, ruta: str):
    r = client.head(ruta)
    if r.status_code == 404:
        pytest.skip(f"{ruta} no existe en esta configuración de rutas")
    assert r.status_code != 405, (
        f"HEAD {ruta} devuelve 405: un monitor de disponibilidad lo leería como caído"
    )
    assert r.status_code == 200


def test_get_y_head_coinciden_en_el_estado(client: TestClient):
    """Si GET dice 200, HEAD tiene que decir 200. Que no se contradigan."""
    g = client.get("/health")
    h = client.head("/health")
    assert g.status_code == h.status_code, (
        f"GET /health dice {g.status_code} y HEAD dice {h.status_code}"
    )


def test_head_no_trae_cuerpo(client: TestClient):
    """Lo exige HTTP: mismas cabeceras, sin cuerpo."""
    h = client.head("/health")
    assert h.content == b""


def test_el_get_sigue_trayendo_los_datos(client: TestClient):
    """Que arreglar HEAD no haya vaciado el GET."""
    g = client.get("/health")
    assert g.status_code == 200
    datos = g.json()
    assert datos.get("status") in ("ok", "degraded")
    assert datos.get("version")


def test_head_a_una_ruta_de_la_interfaz(client: TestClient):
    """La raíz la sirve la SPA; un comprobador de enlaces no debería ver un 405."""
    r = client.head("/")
    assert r.status_code in (200, 404), (
        f"HEAD / devuelve {r.status_code}; 405 significa que el método está prohibido"
    )
