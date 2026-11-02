"""LDAP auth: user provisioning, group mapping, and the login endpoint."""
from __future__ import annotations

from sqlalchemy import select

from app.models import Setting, User
from app.services import ldap_auth

ADMIN_GROUP = "cn=admins,ou=groups,dc=corp,dc=com"


def _enable_ldap(db) -> None:
    db.add(Setting(key="ldap", value={
        "enabled": True, "server_uri": "ldap://dir.example", "bind_dn": "cn=svc",
        "bind_password": "p", "user_base_dn": "ou=people,dc=corp,dc=com",
        "admin_group": ADMIN_GROUP, "default_role": "viewer",
    }))
    db.commit()


CFG = {"admin_group": ADMIN_GROUP, "default_role": "viewer"}


def test_provision_maps_group_to_admin(db):
    viewer = ldap_auth.provision_user(db, {"email": "u@corp.com", "groups": []}, CFG)
    assert viewer.role == "viewer"
    admin = ldap_auth.provision_user(
        db, {"email": "a@corp.com", "groups": [ADMIN_GROUP]}, CFG)
    assert admin.role == "admin"

    again = ldap_auth.provision_user(db, {"email": "u@corp.com", "groups": []}, CFG)
    assert again.id == viewer.id
    assert len(db.scalars(select(User).where(User.email == "u@corp.com")).all()) == 1


def test_login_disabled_by_default(client):
    assert client.post("/api/v1/auth/ldap/login",
                       json={"username": "x", "password": "y"}).status_code == 404


def test_login_success_and_token_works(client, db, monkeypatch):
    _enable_ldap(db)
    monkeypatch.setattr(ldap_auth, "_do_ldap",
                        lambda cfg, u, p: {"email": "ldap.user@corp.com", "groups": []})

    r = client.post("/api/v1/auth/ldap/login",
                    json={"username": "ldap.user", "password": "secret"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == "ldap.user@corp.com"


def test_login_bad_credentials_401(client, db, monkeypatch):
    _enable_ldap(db)
    monkeypatch.setattr(ldap_auth, "_do_ldap", lambda cfg, u, p: None)
    r = client.post("/api/v1/auth/ldap/login",
                    json={"username": "ldap.user", "password": "wrong"})
    assert r.status_code == 401
