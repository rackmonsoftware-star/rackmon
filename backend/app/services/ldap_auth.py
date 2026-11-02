"""LDAP / Active Directory authentication (Fase 3, completing SSO/LDAP).

``provision_user`` (map an LDAP identity to a local user with a role) is
unit-tested. ``_do_ldap`` performs the real bind/search against a directory
server and is isolated/no-cover so tests can inject the result.
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Setting, User, utcnow
from ..security import create_access_token, create_refresh_token, hash_password

log = logging.getLogger("rackmon.ldap")


def _ldap_config(db: Session) -> dict:
    s = get_settings()
    cfg = {
        "enabled": s.ldap_enabled, "server_uri": s.ldap_server_uri,
        "bind_dn": s.ldap_bind_dn, "bind_password": s.ldap_bind_password,
        "user_base_dn": s.ldap_user_base_dn, "user_filter": s.ldap_user_filter,
        "email_attr": s.ldap_email_attr, "group_attr": s.ldap_group_attr,
        "admin_group": s.ldap_admin_group, "default_role": s.ldap_default_role,
    }
    row = db.get(Setting, "ldap")
    if row and row.value:
        cfg.update({k: v for k, v in row.value.items() if v is not None})
    return cfg


def _do_ldap(cfg: dict, username: str, password: str) -> dict | None:  # pragma: no cover - network
    """Bind the service account, find the user, then verify their password by
    binding as them. Returns {'email': ..., 'groups': [...]} or None."""
    from ldap3 import ALL, Connection, Server
    from ldap3.utils.conv import escape_filter_chars

    server = Server(cfg["server_uri"], get_info=ALL)
    svc = Connection(server, cfg["bind_dn"], cfg["bind_password"], auto_bind=True)
    # Escape the username before interpolating into the search filter to prevent
    # LDAP filter injection (e.g. a username of "*)(uid=*").
    flt = cfg["user_filter"].format(username=escape_filter_chars(username))
    svc.search(cfg["user_base_dn"], flt,
               attributes=[cfg["email_attr"], cfg["group_attr"]])
    if not svc.entries:
        return None
    entry = svc.entries[0]
    user_dn = entry.entry_dn
    # Verify the password with a user bind.
    user_conn = Connection(server, user_dn, password)
    if not user_conn.bind():
        return None
    email = _identidad(entry, cfg["email_attr"], username)
    groups = entry[cfg["group_attr"]].values if cfg["group_attr"] in entry else []
    return {"email": email, "groups": [str(g) for g in groups]}


def _identidad(entry, attr: str, username: str) -> str:
    """El identificador local del usuario del directorio. Nunca compartido.

    Antes esto era:

        email = str(entry[attr].value) if attr in entry else username

    y la guarda no servía para nada. ldap3 2.9.1 crea la conexión con
    `return_empty_attributes=True` por defecto, así que un atributo PEDIDO en el
    search() pero que la entrada no tiene vuelve igualmente, con valor None. La
    condición `attr in entry` daba verdadero, y `str(None)` es la cadena "None".

    Resultado: TODOS los usuarios del directorio sin `mail` acababan con el
    mismo correo local, "none", es decir en UNA SOLA cuenta compartida. Y como
    provision_user asciende la cuenta a administrador en cuanto uno de ellos
    pertenece al grupo de admins, bastaba con que hubiera uno para que el resto
    entrara con permisos de administrador y viendo la sesión del anterior. No es
    solo una colisión: es suplantación y escalada de privilegios.

    Se mira el VALOR, no la presencia. Si no hay, se cae al nombre de usuario,
    que es único por definición en el directorio.
    """
    valor = entry[attr].value if attr in entry else None
    if isinstance(valor, (list, tuple)):          # atributo multivalor
        valor = valor[0] if valor else None
    texto = "" if valor is None else str(valor).strip()
    if not texto or texto.lower() in ("none", "null", "nil"):
        log.warning(
            "el usuario %s no tiene valor en el atributo %r; se usa su nombre de "
            "usuario como identidad local para que no comparta cuenta con otros",
            username, attr,
        )
        return username
    return texto


def provision_user(db: Session, attrs: dict, cfg: dict) -> User:
    email = (attrs.get("email") or "").strip().lower()
    if not email:
        raise ValueError("LDAP result missing email")
    admin_group = (cfg.get("admin_group") or "").lower()
    groups = [g.lower() for g in attrs.get("groups", [])]
    is_admin = bool(admin_group) and admin_group in groups

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email, password_hash=hash_password(secrets.token_urlsafe(32)),
            role="admin" if is_admin else cfg["default_role"], is_active=True,
        )
        db.add(user)
        db.flush()
    elif is_admin and user.role != "admin":
        user.role = "admin"
    user.last_login_at = utcnow()
    db.commit()
    return user


def authenticate(db: Session, username: str, password: str) -> User | None:
    # Reject empty credentials up front: many LDAP servers treat a bind with an
    # empty password as a successful ANONYMOUS bind, which would otherwise let a
    # valid username through with no password (an authentication bypass).
    if not username or not password:
        return None
    cfg = _ldap_config(db)
    attrs = _do_ldap(cfg, username, password)
    if attrs is None:
        return None
    return provision_user(db, attrs, cfg)


def issue_tokens(user: User) -> dict:
    return {
        "access_token": create_access_token(user.id, user.role, user.token_version or 0),
        "refresh_token": create_refresh_token(user.id, user.token_version or 0),
        "token_type": "bearer",
    }
