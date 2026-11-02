"""Administration endpoints: users, audit log, notification settings.

User management and settings require the admin role; the audit log is readable
by operators and admins (RF-39..RF-44).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import encrypt
from ..database import get_db
from ..deps import record_audit, require_admin, require_operator
from ..models import Alert, Annotation, ApiKey, AuditLog, Device, Setting, User
from ..schemas import (
    AuditOut,
    SmtpSettingsIn,
    SmtpSettingsOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from ..security import hash_password

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, role=u.role, is_active=u.is_active,
                   mfa_enabled=u.mfa_secret is not None, last_login_at=u.last_login_at)


# --- Users ----------------------------------------------------------------- #


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserOut]:
    return [_user_out(u) for u in db.scalars(select(User).order_by(User.email)).all()]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)) -> UserOut:
    settings = get_settings()
    if len(payload.password) < settings.password_min_length:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Password must be at least {settings.password_min_length} characters")
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password),
                role=payload.role, is_active=True)
    db.add(user)
    record_audit(db, actor_id=actor.id, action="user.create", target_type="user",
                 after={"email": user.email, "role": user.role}, request=request)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, request: Request,
                db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> UserOut:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    settings = get_settings()
    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        if len(data["password"]) < settings.password_min_length:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password too short")
        user.password_hash = hash_password(data.pop("password"))
        user.token_version = (user.token_version or 0) + 1   # admin password reset revokes sessions
    else:
        data.pop("password", None)
    if data.get("is_active") is False and user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot disable your own account")
    for field, value in data.items():
        setattr(user, field, value)
    record_audit(db, actor_id=actor.id, action="user.update", target_type="user",
                 target_id=user.id, request=request)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)) -> Response:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    record_audit(db, actor_id=actor.id, action="user.delete", target_type="user",
                 target_id=user.id, before={"email": user.email}, request=request)
    # Null this user's references before deleting so the delete can't fail on a
    # foreign-key constraint, while the historical rows they touched (audit log,
    # acknowledged/resolved alerts, devices/keys/notes they created) survive.
    db.execute(sa_update(AuditLog).where(AuditLog.actor_id == user_id).values(actor_id=None))
    db.execute(sa_update(Alert).where(Alert.acked_by == user_id).values(acked_by=None))
    db.execute(sa_update(Alert).where(Alert.resolved_by == user_id).values(resolved_by=None))
    db.execute(sa_update(Device).where(Device.created_by == user_id).values(created_by=None))
    db.execute(sa_update(ApiKey).where(ApiKey.created_by == user_id).values(created_by=None))
    db.execute(sa_update(Annotation).where(Annotation.created_by == user_id).values(created_by=None))
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Audit log ------------------------------------------------------------- #


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    action: str | None = Query(default=None),
    actor_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
    _: User = Depends(require_operator),
) -> list[AuditOut]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    rows = db.scalars(stmt).all()
    ids = {r.actor_id for r in rows if r.actor_id is not None}
    emails = dict(
        db.execute(select(User.id, User.email).where(User.id.in_(ids))).all()
    ) if ids else {}
    out: list[AuditOut] = []
    for a in rows:
        o = AuditOut.model_validate(a)
        o.actor_email = emails.get(a.actor_id)
        out.append(o)
    return out


# --- SMTP settings --------------------------------------------------------- #

_SMTP_KEY = "smtp"


@router.get("/settings/smtp", response_model=SmtpSettingsOut)
def get_smtp(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> SmtpSettingsOut:
    row = db.get(Setting, _SMTP_KEY)
    v = dict(row.value) if row and row.value else {}
    return SmtpSettingsOut(
        host=v.get("host"), port=v.get("port", 587), user=v.get("user"),
        has_password=bool(v.get("password_enc")), use_tls=v.get("use_tls", True),
        use_ssl=v.get("use_ssl", False), from_address=v.get("from_address", "rackmon@localhost"),
        recipients=v.get("recipients", []),
    )


@router.put("/settings/smtp", response_model=SmtpSettingsOut)
def put_smtp(payload: SmtpSettingsIn, request: Request, db: Session = Depends(get_db),
             actor: User = Depends(require_admin)) -> SmtpSettingsOut:
    row = db.get(Setting, _SMTP_KEY)
    existing = dict(row.value) if row and row.value else {}
    value = {
        "host": payload.host, "port": payload.port, "user": payload.user,
        "use_tls": payload.use_tls, "use_ssl": payload.use_ssl,
        "from_address": payload.from_address, "recipients": payload.recipients,
    }
    # Preserve existing password unless a new one is supplied.
    if payload.password:
        value["password_enc"] = encrypt(payload.password)
    elif existing.get("password_enc"):
        value["password_enc"] = existing["password_enc"]

    if row:
        row.value = value
    else:
        db.add(Setting(key=_SMTP_KEY, value=value))
    record_audit(db, actor_id=actor.id, action="settings.smtp", target_type="settings",
                 target_id=_SMTP_KEY, request=request)
    db.commit()
    return get_smtp(db=db, _=actor)


@router.post("/settings/smtp/test")
def test_smtp(to: str, db: Session = Depends(get_db),
              _: User = Depends(require_admin)) -> dict:  # pragma: no cover - network
    from ..services.notifier import send_test_email

    try:
        send_test_email(db, to)
    except Exception as exc:
        return {"ok": False, "detail": f"Send failed: {exc}"}
    return {"ok": True, "detail": f"Test email sent to {to}"}


# --------------------------------------------------------------------------- #
# API keys (RF-48): long-lived programmatic credentials
# --------------------------------------------------------------------------- #
from pydantic import BaseModel  # noqa: E402

from ..security import generate_api_key  # noqa: E402


class ApiKeyCreateIn(BaseModel):
    name: str


class ApiKeyOut(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked: bool = False

    model_config = {"from_attributes": True}


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # full secret — shown exactly once


@router.get("/apikeys", response_model=list[ApiKeyOut])
def list_api_keys(db: Session = Depends(get_db),
                  _: User = Depends(require_admin)) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.id.desc())).all())


@router.post("/apikeys", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
def create_api_key(payload: ApiKeyCreateIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)) -> ApiKeyCreatedOut:
    full, prefix, key_hash = generate_api_key()
    row = ApiKey(name=payload.name, prefix=prefix, key_hash=key_hash, created_by=actor.id)
    db.add(row)
    db.flush()
    record_audit(db, actor_id=actor.id, action="apikey.create", target_type="apikey",
                 target_id=row.id, after={"name": row.name}, request=request)
    db.commit()
    db.refresh(row)
    return ApiKeyCreatedOut(
        id=row.id, name=row.name, prefix=row.prefix, created_at=row.created_at,
        last_used_at=row.last_used_at, revoked=row.revoked, key=full,
    )


class ApiKeyUpdate(BaseModel):
    name: str


@router.patch("/apikeys/{key_id}", response_model=ApiKeyOut)
def rename_api_key(key_id: int, payload: ApiKeyUpdate, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)) -> ApiKey:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    row.name = payload.name
    record_audit(db, actor_id=actor.id, action="apikey.rename", target_type="apikey",
                 target_id=key_id, request=request)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/apikeys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(key_id: int, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)) -> Response:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    row.revoked = True
    record_audit(db, actor_id=actor.id, action="apikey.revoke", target_type="apikey",
                 target_id=key_id, request=request)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# Configuration backup / restore (Fase 2)
# --------------------------------------------------------------------------- #
from ..models import AlertRule, MetricCatalog  # noqa: E402

_DEVICE_KEYS = ("name", "hostname", "ip", "snmp_version", "snmp_community_enc",
                "snmp_port", "vendor", "model", "rack", "position_u", "size_u",
                "tags", "enabled")
_RULE_KEYS = ("name", "scope_type", "scope_ref", "metric", "operator", "threshold",
              "for_seconds", "severity", "throttle_seconds", "enabled")
_METRIC_KEYS = ("name", "label", "unit", "oid", "scale", "poll_interval_s", "enabled")


def _pick(obj, keys) -> dict:
    return {k: getattr(obj, k) for k in keys}


class BackupIn(BaseModel):
    devices: list[dict] = []
    rules: list[dict] = []
    settings: list[dict] = []


@router.get("/backup")
def export_backup(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> dict:
    devices = []
    for d in db.scalars(select(Device)).all():
        row = _pick(d, _DEVICE_KEYS)
        row["metrics"] = [_pick(m, _METRIC_KEYS) for m in d.metrics]
        devices.append(row)
    rules = [_pick(r, _RULE_KEYS) for r in db.scalars(select(AlertRule)).all()]
    settings = [{"key": s.key, "value": s.value} for s in db.scalars(select(Setting)).all()]
    return {"version": 1, "devices": devices, "rules": rules, "settings": settings}


@router.post("/restore")
def restore_backup(payload: BackupIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)) -> dict:
    known_ips = {ip for (ip,) in db.execute(select(Device.ip)).all()}
    known_rules = {n for (n,) in db.execute(select(AlertRule.name)).all()}
    dev_created = dev_skipped = rule_created = rule_skipped = 0

    for d in payload.devices:
        if d.get("ip") in known_ips:
            dev_skipped += 1
            continue
        fields = {k: d.get(k) for k in _DEVICE_KEYS if k in d}
        fields.setdefault("name", d.get("ip", "restored"))
        # Validate the fields the read model constrains, so a corrupt/edited backup
        # can't store a value that later 500s every device-serializing endpoint.
        pu = fields.get("position_u")
        if fields.get("snmp_version") not in (None, "1", "2c", "3") or (
            pu is not None and not (isinstance(pu, int) and 1 <= pu <= 60)
        ):
            dev_skipped += 1
            continue
        device = Device(**fields, created_by=actor.id)
        db.add(device)
        db.flush()
        for m in d.get("metrics", []):
            db.add(MetricCatalog(device_id=device.id,
                                 **{k: m.get(k) for k in _METRIC_KEYS if k in m}))
        known_ips.add(d.get("ip"))
        dev_created += 1

    for r in payload.rules:
        if r.get("name") in known_rules:
            rule_skipped += 1
            continue
        db.add(AlertRule(**{k: r.get(k) for k in _RULE_KEYS if k in r}))
        known_rules.add(r.get("name"))
        rule_created += 1

    for s in payload.settings:
        key = s.get("key")
        # Only allow the keys the dedicated settings endpoint permits — restore must
        # not be a backdoor to write oidc/ldap/smtp or other gated config groups.
        if not key or key not in _SETTINGS_WHITELIST:
            continue
        row = db.get(Setting, key)
        if row:
            row.value = s.get("value") or {}
        else:
            db.add(Setting(key=key, value=s.get("value") or {}))

    record_audit(db, actor_id=actor.id, action="config.restore", target_type="config",
                 target_id=None, after={"devices": dev_created, "rules": rule_created},
                 request=request)
    db.commit()
    return {"devices_created": dev_created, "devices_skipped": dev_skipped,
            "rules_created": rule_created, "rules_skipped": rule_skipped,
            "settings_restored": len(payload.settings)}


# --------------------------------------------------------------------------- #
# Runtime settings (no-secret config groups, editable from the UI)
# --------------------------------------------------------------------------- #
_SETTINGS_WHITELIST = {"report_schedule", "escalation", "status_page", "branding", "updates"}


class SettingValueIn(BaseModel):
    value: dict


@router.get("/settings/{key}")
def get_setting(key: str, db: Session = Depends(get_db),
                _: User = Depends(require_admin)) -> dict:
    if key not in _SETTINGS_WHITELIST:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown setting")
    row = db.get(Setting, key)
    return {"key": key, "value": row.value if row else {}}


@router.put("/settings/{key}")
def put_setting(key: str, payload: SettingValueIn, request: Request,
                db: Session = Depends(get_db), actor: User = Depends(require_admin)) -> dict:
    if key not in _SETTINGS_WHITELIST:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown setting")
    row = db.get(Setting, key)
    if row:
        row.value = payload.value
    else:
        db.add(Setting(key=key, value=payload.value))
    record_audit(db, actor_id=actor.id, action="setting.update", target_type="setting",
                 target_id=key, request=request)
    db.commit()
    return {"key": key, "value": payload.value}
