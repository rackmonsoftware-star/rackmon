"""SSO via OpenID Connect (Fase 3).

The authorization-URL construction and the user-provisioning logic are
unit-tested. ``exchange_code`` performs the token-endpoint HTTP round-trip with
the identity provider and is isolated/no-cover so tests can inject claims.
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting, User, utcnow
from ..security import create_access_token, create_refresh_token, hash_password

log = logging.getLogger("rackmon.sso")


def _oidc_config(db: Session) -> dict:
    s = get_settings()
    cfg = {
        "enabled": s.oidc_enabled, "issuer": s.oidc_issuer, "client_id": s.oidc_client_id,
        "client_secret": s.oidc_client_secret, "redirect_uri": s.oidc_redirect_uri,
        "authorization_endpoint": s.oidc_authorization_endpoint,
        "token_endpoint": s.oidc_token_endpoint, "jwks_uri": s.oidc_jwks_uri,
        "scopes": s.oidc_scopes,
        "default_role": s.oidc_default_role, "admin_emails": list(s.oidc_admin_emails),
    }
    row = db.get(Setting, "oidc")
    if row and row.value:
        cfg.update({k: v for k, v in row.value.items() if v is not None})
    issuer = (cfg.get("issuer") or "").rstrip("/")
    if not cfg.get("authorization_endpoint"):
        cfg["authorization_endpoint"] = f"{issuer}/authorize"
    if not cfg.get("token_endpoint"):
        cfg["token_endpoint"] = f"{issuer}/token"
    if not cfg.get("jwks_uri"):
        cfg["jwks_uri"] = f"{issuer}/.well-known/jwks.json"
    return cfg


def new_state() -> str:
    return secrets.token_urlsafe(24)


def build_auth_url(db: Session, state: str) -> str:
    cfg = _oidc_config(db)
    params = {
        "response_type": "code", "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"], "scope": cfg["scopes"], "state": state,
    }
    return f"{cfg['authorization_endpoint']}?{urlencode(params)}"


def exchange_code(db: Session, code: str) -> dict:  # pragma: no cover - network
    """Exchange an auth code for tokens and return the ID-token claims."""
    import httpx
    import jwt

    cfg = _oidc_config(db)
    resp = httpx.post(cfg["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": cfg["redirect_uri"], "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }, timeout=10.0)
    resp.raise_for_status()
    id_token = resp.json()["id_token"]
    # Verify the ID token: signature against the provider's JWKS, plus audience,
    # issuer and expiry. Without this a forged token could impersonate any user.
    signing_key = jwt.PyJWKClient(cfg["jwks_uri"]).get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "RS384", "RS512", "ES256"],
        audience=cfg["client_id"],
        issuer=cfg["issuer"] or None,
        options={"require": ["exp", "iat"]},
    )


def provision_user(db: Session, claims: dict) -> User:
    """Find or create a local user from verified OIDC claims."""
    cfg = _oidc_config(db)
    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise ValueError("OIDC claims missing email")
    # An email the IdP marks as UNVERIFIED is attacker-settable at many providers, so
    # it is rejected outright — it cannot sign in at all, let alone become admin.
    #
    # A claim that is ABSENT is a different thing from one that is false. Plenty of
    # enterprise providers never send `email_verified`: Entra ID does not, nor do many
    # Okta setups. Treating absent as "unverified" silently dropped every admin_emails
    # mapping on those providers — the administrator signed in as a viewer with no
    # error anywhere — which made the Pro SSO feature quietly useless for a large part
    # of its intended market. Absent is therefore trusted here, exactly as it already
    # was for signing in; the operator who configured this IdP already chose to trust
    # it, and RackMon has no better source of truth than they do.
    ev = claims.get("email_verified")
    if ev is None:
        email_trusted = True
        claim_ausente = True
    else:
        email_trusted = ev is True or (isinstance(ev, str) and ev.strip().lower() in ("true", "1", "yes"))
        claim_ausente = False
        if not email_trusted:
            raise ValueError("OIDC email is not verified by the identity provider")

    is_admin = email_trusted and email in [e.lower() for e in cfg["admin_emails"]]

    # Rastro de auditoría: si se conceden permisos de administrador sin que el
    # proveedor haya afirmado nada sobre el correo, queda escrito. Es el único
    # camino por el que una configuración floja del IdP podría dar admin de más.
    if is_admin and claim_ausente:
        log.warning(
            "admin granted to %s via SSO: the identity provider sent no "
            "'email_verified' claim, so the address was trusted as configured",
            email,
        )

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            password_hash=hash_password(secrets.token_urlsafe(32)),  # unusable password
            role="admin" if is_admin else cfg["default_role"],
            is_active=True,
        )
        db.add(user)
        db.flush()
    elif is_admin and user.role != "admin":
        user.role = "admin"
    user.last_login_at = utcnow()
    db.commit()
    return user


def issue_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, user.role, user.token_version or 0),
        "refresh_token": create_refresh_token(user.id, user.token_version or 0),
        "token_type": "bearer",
    }
