"""Authentication endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import jwt
import pyotp
from urllib.parse import quote

from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..deps import get_current_user, record_audit
from ..models import User, ensure_aware, utcnow
from ..schemas import LoginRequest, RefreshRequest, TokenPair, UserOut
from ..security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)

log = logging.getLogger("rackmon.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "rackmon_refresh"

# A throwaway hash so an unknown-email login still runs one argon2 verify. Without
# it, a missing account returns instantly while a wrong password pays the hashing
# cost — a timing oracle that lets an attacker enumerate valid emails.
_DUMMY_HASH = hash_password("rackmon-login-timing-equaliser")


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, role=user.role, is_active=user.is_active,
        mfa_enabled=user.mfa_secret is not None, last_login_at=user.last_login_at,
    )


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE, token, httponly=True, samesite="lax",
        secure=settings.environment == "production",
        max_age=settings.refresh_token_ttl_days * 86400, path="/api/v1/auth",
    )


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, response: Response,
          db: Session = Depends(get_db)) -> TokenPair:
    now = datetime.now(timezone.utc)
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    generic = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if user is None:
        # Run a dummy verify so the response time matches the wrong-password path
        # (constant-time w.r.t. account existence) — prevents email enumeration.
        verify_password(payload.password, _DUMMY_HASH)
        raise generic
    locked_until = ensure_aware(user.locked_until)
    if locked_until and locked_until > now:
        raise HTTPException(status.HTTP_423_LOCKED, "Account temporarily locked")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")

    if not verify_password(payload.password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_login_attempts:
            from datetime import timedelta

            user.locked_until = now + timedelta(seconds=settings.lockout_seconds)
            user.failed_logins = 0
        db.commit()
        raise generic

    # Optional TOTP second factor. A wrong/missing OTP counts toward the SAME
    # lockout as a wrong password, so the second factor can't be brute-forced.
    if user.mfa_secret:
        if not payload.otp or not pyotp.TOTP(user.mfa_secret).verify(payload.otp, valid_window=1):
            user.failed_logins += 1
            if user.failed_logins >= settings.max_login_attempts:
                from datetime import timedelta

                user.locked_until = now + timedelta(seconds=settings.lockout_seconds)
                user.failed_logins = 0
            db.commit()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing OTP")

    # Transparent hash upgrade if parameters changed.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    record_audit(db, actor_id=user.id, action="login", target_type="user",
                 target_id=user.id, request=request)
    db.commit()

    access = create_access_token(user.id, user.role, user.token_version or 0)
    refresh = create_refresh_token(user.id, user.token_version or 0)
    _set_refresh_cookie(response, refresh)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, request: Request, response: Response,
            db: Session = Depends(get_db)) -> TokenPair:
    token = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    try:
        claims = decode_token(token, expected_type="refresh")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")

    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or missing")
    if claims.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked; sign in again")

    access = create_access_token(user.id, user.role, user.token_version or 0)
    new_refresh = create_refresh_token(user.id, user.token_version or 0)
    _set_refresh_cookie(response, new_refresh)
    return TokenPair(access_token=access, refresh_token=new_refresh)


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user)) -> dict:
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    return {"detail": "logged out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return _user_out(user)


# --------------------------------------------------------------------------- #
# SSO (OpenID Connect) — Fase 3
# --------------------------------------------------------------------------- #
@router.get("/oidc/login")
def oidc_login(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    from ..services import sso

    cfg = sso._oidc_config(db)
    if not cfg.get("enabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not enabled")
    state = sso.new_state()
    # Bind the state to this browser (CSRF): the callback must present the same value.
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie("oidc_state", state, max_age=600, httponly=True,
                        secure=secure, samesite="lax", path="/api/v1/auth")
    return {"authorization_url": sso.build_auth_url(db, state), "state": state}


# La ruta de la SPA que recoge el resultado del proveedor de identidad. Tiene que
# existir en el enrutador del frontend; hay una prueba que lo comprueba, porque si
# alguien la renombra allí el inicio de sesión por SSO deja de funcionar y nada lo
# dice: el navegador se queda en una página en blanco.
RUTA_DE_VUELTA_SSO = "/auth/callback"


@router.get("/oidc/callback")
def oidc_callback(code: str, request: Request, response: Response, state: str | None = None,
                  db: Session = Depends(get_db)):
    from ..services import sso

    cfg = sso._oidc_config(db)
    if not cfg.get("enabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not enabled")
    # CSRF: the returned state must match the value bound to this browser at login.
    expected_state = request.cookies.get("oidc_state")
    response.delete_cookie("oidc_state", path="/api/v1/auth")
    if not state or not expected_state or state != expected_state:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or missing OAuth state")
    try:
        claims = sso.exchange_code(db, code)
        user = sso.provision_user(db, claims)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    record_audit(db, actor_id=user.id, action="auth.sso_login", target_type="user",
                 target_id=user.id, request=request)
    db.commit()
    tokens = sso.issue_tokens(user)

    # Se DEVUELVE UNA REDIRECCIÓN, no un JSON.
    #
    # Aquí llega el NAVEGADOR, no un cliente de API: el proveedor de identidad
    # redirige la ventana entera a esta dirección. Hasta la 1.2.9 esto contestaba
    # con `TokenPair`, así que el usuario terminaba mirando un volcado de JSON con
    # sus propios tokens en pantalla, y la aplicación nunca llegaba a enterarse de
    # que había iniciado sesión. No había tampoco ninguna ruta en el frontend que
    # recogiera nada. Es decir: el SSO, que es una función de pago y de las más
    # anunciadas, no podía completar un inicio de sesión de ninguna manera.
    #
    # Los tokens viajan en el FRAGMENTO (#) y no en la consulta (?) a propósito:
    # el fragmento no se manda al servidor, así que no acaba en los registros de
    # acceso ni en la cabecera Referer hacia terceros. La página de vuelta los
    # guarda y limpia la barra de direcciones en cuanto los recoge.
    destino = (
        f"{RUTA_DE_VUELTA_SSO}"
        f"#access_token={quote(tokens['access_token'])}"
        f"&refresh_token={quote(tokens['refresh_token'])}"
    )
    salida = RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
    # La cookie se borra AQUÍ y no en `response`: al devolver una respuesta nueva,
    # las cabeceras que se hubieran puesto en la inyectada se quedan por el camino
    # y el estado de un intento ya consumido seguiría vivo diez minutos más.
    salida.delete_cookie("oidc_state", path="/api/v1/auth")
    return salida


# --------------------------------------------------------------------------- #
# LDAP / Active Directory login — Fase 3
# --------------------------------------------------------------------------- #
from pydantic import BaseModel  # noqa: E402


class LdapLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/ldap/login", response_model=TokenPair)
def ldap_login(payload: LdapLoginRequest, request: Request,
               db: Session = Depends(get_db)) -> TokenPair:
    from ..services import ldap_auth

    if not ldap_auth._ldap_config(db).get("enabled"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LDAP is not enabled")
    try:
        user = ldap_auth.authenticate(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid LDAP credentials")
    record_audit(db, actor_id=user.id, action="auth.ldap_login", target_type="user",
                 target_id=user.id, request=request)
    db.commit()
    tokens = ldap_auth.issue_tokens(user)
    return TokenPair(access_token=tokens["access_token"], refresh_token=tokens["refresh_token"])


@router.get("/sso-config")
def sso_config(db: Session = Depends(get_db)) -> dict:
    """Public: tells the login page which SSO options to offer (no secrets)."""
    from ..services import sso, ldap_auth

    return {
        "oidc_enabled": bool(sso._oidc_config(db).get("enabled")),
        "ldap_enabled": bool(ldap_auth._ldap_config(db).get("enabled")),
        # La demo pública entra sin teclear nada. Apagado por defecto.
        "demo_mode": get_settings().demo_mode,
    }


@router.post("/demo", response_model=TokenPair)
def demo_login(request: Request, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    """Entrada directa a la demo pública, sin usuario ni contraseña.

    Existe porque mucha gente abandona la demo antes de probarla solo por tener
    que teclear unas credenciales. Sólo funciona con ``RACKMON_DEMO_MODE=true``
    —apagado por defecto, así que ninguna instalación de cliente lo expone— y
    **sólo entrega una cuenta de rol viewer**: si la cuenta configurada tuviera
    cualquier otro rol, esto se niega en vez de repartir permisos de escritura.
    """
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    email = (settings.demo_user_email or settings.viewer_email or "").strip().lower()
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if user is None or not user.is_active:
        log.warning("demo mode is on but the demo account '%s' does not exist", email)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Demo account unavailable")

    # Cinturón y tirantes: aunque alguien apunte RACKMON_DEMO_USER_EMAIL a una
    # cuenta con permisos, esta puerta nunca los entrega.
    if user.role != "viewer":
        log.error("refusing demo login: '%s' has role '%s', not viewer", email, user.role)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Demo account unavailable")

    user.last_login_at = utcnow()
    record_audit(db, actor_id=user.id, action="login.demo", target_type="user",
                 target_id=user.id, request=request)
    db.commit()

    access = create_access_token(user.id, user.role, user.token_version or 0)
    refresh = create_refresh_token(user.id, user.token_version or 0)
    _set_refresh_cookie(response, refresh)
    return TokenPair(access_token=access, refresh_token=refresh)


# --------------------------------------------------------------------------- #
# Self-service: change password + MFA enrollment
# --------------------------------------------------------------------------- #
class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if len(payload.new_password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Password must be at least 8 characters")
    user.password_hash = hash_password(payload.new_password)
    user.token_version = (user.token_version or 0) + 1   # revoke all previously-issued sessions
    db.commit()
    record_audit(db, actor_id=user.id, action="change_password", target_type="user", target_id=user.id)
    return {"detail": "Password updated"}


@router.post("/mfa/setup")
def mfa_setup(user: User = Depends(get_current_user)) -> dict:
    """Generate a fresh TOTP secret + provisioning URI (not persisted until enabled)."""
    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="RackMon")
    return {"secret": secret, "otpauth_url": uri}


class MfaEnableRequest(BaseModel):
    secret: str
    otp: str


@router.post("/mfa/enable")
def mfa_enable(payload: MfaEnableRequest, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)) -> dict:
    if not pyotp.TOTP(payload.secret).verify(payload.otp, valid_window=1):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid verification code")
    user.mfa_secret = payload.secret
    db.commit()
    record_audit(db, actor_id=user.id, action="enable_mfa", target_type="user", target_id=user.id)
    return {"detail": "Two-factor authentication enabled", "mfa_enabled": True}


class MfaDisableRequest(BaseModel):
    password: str


@router.post("/mfa/disable")
def mfa_disable(payload: MfaDisableRequest, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> dict:
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    user.mfa_secret = None
    db.commit()
    record_audit(db, actor_id=user.id, action="disable_mfa", target_type="user", target_id=user.id)
    return {"detail": "Two-factor authentication disabled", "mfa_enabled": False}
