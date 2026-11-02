"""Marca blanca: el endpoint publico y los valores personalizados.

Fue funcion de pago hasta la 1.3.0; ahora la tiene todo el mundo."""


def test_branding_is_public_and_defaults_to_rackmon(client):
    r = client.get("/api/v1/branding")  # no auth
    assert r.status_code == 200
    body = r.json()
    assert body["product_name"] == "RackMon"
    assert body["accent"].startswith("#")


def test_branding_custom_with_license(client, admin_headers):
    r = client.put("/api/v1/admin/settings/branding", headers=admin_headers,
                   json={"value": {"product_name": "AcmeMon", "accent": "#ff8800"}})
    assert r.status_code == 200
    body = client.get("/api/v1/branding").json()
    assert body["product_name"] == "AcmeMon"
    assert body["accent"] == "#ff8800"


def test_la_marca_personalizada_se_aplica_sin_licencia(client, admin_headers):
    """Desde la 1.3.0 la marca blanca es de todos: ya no pide licencia."""
    client.put("/api/v1/admin/settings/branding", headers=admin_headers,
               json={"value": {"product_name": "AcmeMon", "accent": "#ff8800"}})
    body = client.get("/api/v1/branding").json()
    assert body["product_name"] == "AcmeMon", (
        "la marca personalizada se ignora: el producto sigue cerrado tras una licencia"
    )
    assert body["accent"] == "#ff8800"
