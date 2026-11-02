"""SSO (OpenID Connect): auth URL, user provisioning, and callback flow."""
from __future__ import annotations

from sqlalchemy import select

from app.models import Setting, User
from app.services import sso


def _enable_oidc(db, admin_emails=None) -> None:
    db.add(Setting(key="oidc", value={
        "enabled": True, "issuer": "https://idp.example", "client_id": "cid",
        "client_secret": "sec", "redirect_uri": "https://app.example/cb",
        "default_role": "viewer", "admin_emails": admin_emails or [],
    }))
    db.commit()


def test_login_returns_authorization_url(client, db):
    _enable_oidc(db)
    r = client.get("/api/v1/auth/oidc/login")
    assert r.status_code == 200
    url = r.json()["authorization_url"]
    assert url.startswith("https://idp.example/authorize?")
    assert "client_id=cid" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example%2Fcb" in url
    assert "state=" in url


def test_login_disabled_by_default(client):
    assert client.get("/api/v1/auth/oidc/login").status_code == 404


def test_provision_creates_and_maps_roles(db):
    _enable_oidc(db, admin_emails=["boss@corp.com"])
    u1 = sso.provision_user(db, {"email": "user@corp.com"})
    assert u1.role == "viewer"
    boss = sso.provision_user(db, {"email": "boss@corp.com"})
    assert boss.role == "admin"

    # Idempotent: same email doesn't create a duplicate.
    again = sso.provision_user(db, {"email": "user@corp.com"})
    assert again.id == u1.id
    assert len(db.scalars(select(User).where(User.email == "user@corp.com")).all()) == 1


def test_provision_requires_email(db):
    _enable_oidc(db)
    try:
        sso.provision_user(db, {"name": "no email"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_callback_issues_working_token(client, db, monkeypatch):
    _enable_oidc(db)
    monkeypatch.setattr(sso, "exchange_code",
                        lambda db_, code: {"email": "sso.user@corp.com", "name": "SSO User"})

    # Start login to obtain the CSRF state (the server sets it as a cookie the
    # TestClient will send back on the callback).
    state = client.get("/api/v1/auth/oidc/login").json()["state"]
    # Sin seguir la redirección: lo que importa es ADÓNDE manda al navegador.
    r = client.get(f"/api/v1/auth/oidc/callback?code=abc123&state={state}",
                   follow_redirects=False)
    assert r.status_code == 303, (
        f"el callback contestó {r.status_code}; si vuelve a devolver un JSON, el "
        "usuario termina mirando sus propios tokens en pantalla y la aplicación "
        "no llega a iniciar sesión"
    )
    from urllib.parse import parse_qs, urlparse

    destino = urlparse(r.headers["location"])
    assert destino.path == "/auth/callback"
    frag = parse_qs(destino.fragment)
    token = frag["access_token"][0]
    assert token

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "sso.user@corp.com"


def test_callback_rejects_forged_state(client, db, monkeypatch):
    _enable_oidc(db)
    monkeypatch.setattr(sso, "exchange_code", lambda db_, code: {"email": "x@corp.com"})
    client.get("/api/v1/auth/oidc/login")  # binds a real state cookie to this client
    # A state that does not match the cookie (CSRF / stolen-code) is rejected.
    r = client.get("/api/v1/auth/oidc/callback?code=abc&state=forged-value")
    assert r.status_code == 400


def test_sso_config_endpoint(client, db):
    r = client.get("/api/v1/auth/sso-config")
    assert r.status_code == 200
    # Se comprueban las claves que importan, no el diccionario entero: este
    # endpoint le dice a la pantalla de login qué ofrecer, y añadir una opción
    # nueva (como el modo demo) no debe romper un test de SSO.
    datos = r.json()
    assert datos["oidc_enabled"] is False
    assert datos["ldap_enabled"] is False
    _enable_oidc(db)
    assert client.get("/api/v1/auth/sso-config").json()["oidc_enabled"] is True


# --- email_verified: los tres casos, fijados (24-sep) -----------------------


def test_admin_mapping_works_when_idp_omits_email_verified(db, caplog):
    """Entra ID y muchas configuraciones de Okta NO envían `email_verified`.
    Tratarlo como "no verificado" dejaba al administrador entrando como simple
    usuario, en silencio y sin error: la función Pro no servía para nada en
    buena parte de su mercado."""
    import logging

    _enable_oidc(db, admin_emails=["boss@corp.com"])
    with caplog.at_level(logging.WARNING, logger="rackmon.sso"):
        boss = sso.provision_user(db, {"email": "boss@corp.com"})  # sin el campo
    assert boss.role == "admin"
    # y queda rastro de que se concedió sin afirmación del proveedor
    assert any("email_verified" in r.message for r in caplog.records), \
        "conceder admin con el claim ausente debe dejar rastro en el registro"


def test_explicitly_unverified_email_is_still_refused(db):
    """El caso peligroso de verdad no cambia: si el proveedor dice que el correo
    NO está verificado, no entra. Ni como usuario ni como nada."""
    import pytest

    _enable_oidc(db, admin_emails=["boss@corp.com"])
    with pytest.raises(ValueError):
        sso.provision_user(db, {"email": "boss@corp.com", "email_verified": False})


def test_verified_email_maps_to_admin_without_warning(db, caplog):
    """Cuando el proveedor sí lo afirma, funciona y no ensucia el registro."""
    import logging

    _enable_oidc(db, admin_emails=["boss@corp.com"])
    with caplog.at_level(logging.WARNING, logger="rackmon.sso"):
        boss = sso.provision_user(db, {"email": "boss@corp.com", "email_verified": True})
    assert boss.role == "admin"
    assert not any("email_verified" in r.message for r in caplog.records)


def test_a_non_admin_email_never_becomes_admin(db):
    """La lista sigue mandando: estar fuera de admin_emails es ser viewer,
    afirme lo que afirme el proveedor."""
    _enable_oidc(db, admin_emails=["boss@corp.com"])
    otro = sso.provision_user(db, {"email": "cualquiera@corp.com", "email_verified": True})
    assert otro.role == "viewer"
