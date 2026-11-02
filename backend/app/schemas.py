"""Pydantic v2 schemas for the public API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Operator = Literal[">", "<", ">=", "<=", "==", "!="]
ScopeType = Literal["device", "tag", "global"]
SeverityT = Literal["info", "warning", "critical"]
RoleT = Literal["admin", "operator", "viewer"]

# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    otp: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    role: RoleT
    is_active: bool
    mfa_enabled: bool = False
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: RoleT = "viewer"


class UserUpdate(BaseModel):
    role: RoleT | None = None
    is_active: bool | None = None
    password: str | None = None
    email: str | None = None


# --------------------------------------------------------------------------- #
# Devices & metrics catalog
# --------------------------------------------------------------------------- #


class MetricCatalogIn(BaseModel):
    name: str
    label: str = ""
    oid: str | None = None
    unit: str = ""
    # Factor para convertir lo que devuelve el aparato en la unidad de `unit`.
    # 0.1 para los OID que dan décimas (iDRAC, APC). 1 = tal cual.
    scale: float = Field(default=1.0, gt=0)
    poll_interval_s: int = Field(default=30, ge=5, le=3600)
    enabled: bool = True

    @field_validator("scale", mode="before")
    @classmethod
    def _escala_por_defecto(cls, v):
        # Las filas creadas antes de que existiera la columna la tienen a NULL.
        # Ahí "sin escala" significa 1, no un error de validación.
        return 1.0 if v in (None, 0) else v


class MetricCatalogOut(MetricCatalogIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int


def _validar_host(v: str) -> str:
    """Valida el destino SNMP de un dispositivo.

    Acepta una dirección IPv4/IPv6 **o un nombre de host**, porque SNMP puede
    apuntar a cualquiera de los dos. Lo que no acepta es algo que *pretende* ser
    una IPv4 y no lo es: `192.168.1.300` pasaba como si fuese un nombre de host,
    y el resultado era un dispositivo que no respondía nunca sin que nadie
    supiera por qué. Un error de dedo en la acción principal del producto tiene
    que avisarse en el momento, no convertirse en un equipo muerto.
    """
    import ipaddress
    import re

    v = (v or "").strip()
    if not v or any(c.isspace() for c in v) or len(v) > 255:
        raise ValueError("ip must be a non-empty host or address without spaces")

    # ¿Tiene forma de IPv4 (cuatro grupos de dígitos)? Entonces debe serlo.
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", v):
        try:
            ipaddress.IPv4Address(v)
        except ValueError:
            raise ValueError(f"'{v}' looks like an IPv4 address but is not a valid one")
    return v


class DeviceBase(BaseModel):
    name: str
    hostname: str | None = None
    ip: str
    snmp_version: Literal["1", "2c", "3"] = "2c"
    snmp_port: int = Field(default=161, ge=1, le=65535)
    vendor: str | None = None
    model: str | None = None
    rack: str | None = None
    position_u: int | None = Field(default=None, ge=1, le=60)
    size_u: int = Field(default=1, ge=1, le=20)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        return sorted({t.strip() for t in v if t and t.strip()})


class DeviceCreate(DeviceBase):
    snmp_community: str | None = None  # plaintext in; stored encrypted
    snmpv3: dict | None = None  # SNMPv3 creds (security_name, auth_protocol, auth_key, priv_protocol, priv_key)
    metrics: list[MetricCatalogIn] | None = None

    # Input-only validation (kept off DeviceBase so it never runs on DeviceOut and
    # can't fail serialization of already-stored rows).
    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name must not be empty")
        if len(v) > 120:
            raise ValueError("name too long (max 120)")
        return v

    @field_validator("ip")
    @classmethod
    def _clean_ip(cls, v: str) -> str:
        return _validar_host(v)


class DeviceUpdate(BaseModel):
    name: str | None = None
    hostname: str | None = None
    ip: str | None = None
    snmp_version: Literal["1", "2c", "3"] | None = None
    snmp_port: int | None = Field(default=None, ge=1, le=65535)
    snmp_community: str | None = None
    vendor: str | None = None
    model: str | None = None
    rack: str | None = None
    position_u: int | None = Field(default=None, ge=1, le=60)
    size_u: int | None = Field(default=None, ge=1, le=20)
    tags: list[str] | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _u_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("name must not be empty")
        return v

    @field_validator("ip")
    @classmethod
    def _u_ip(cls, v: str | None) -> str | None:
        # Exactamente la misma regla que al crear. Ya se rechazaban los vacíos y
        # los espacios, pero no lo que aparenta ser una IPv4 sin serlo, así que
        # por aquí se colaba igual un 192.168.1.300.
        return None if v is None else _validar_host(v)


class DeviceOut(DeviceBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    has_community: bool = False
    has_snmpv3: bool = False
    in_maintenance: bool = False
    metrics: list[MetricCatalogOut] = Field(default_factory=list)


class DeviceStatusOut(BaseModel):
    """Device plus its live rollup for dashboards."""
    device: DeviceOut
    status: Literal["ok", "warning", "critical", "nodata", "maintenance"]
    temperature: float | None = None
    # De QUÉ métrica salió esa temperatura. Sin esto la interfaz no puede pintarla
    # bien: 32 °C de aire de entrada es crítico y 32 °C de CPU es un equipo en
    # reposo, y el color tiene que significar lo mismo que el estado.
    temperature_metric: str | None = None
    last_seen: datetime | None = None
    firing_alerts: int = 0


class MaintenanceRequest(BaseModel):
    minutes: int = Field(ge=1, le=60 * 24 * 30)


# --------------------------------------------------------------------------- #
# Metrics query
# --------------------------------------------------------------------------- #


class MetricSample(BaseModel):
    time: datetime = Field(serialization_alias="t")
    value: float = Field(serialization_alias="v")
    status: int = 0


class MetricSeriesOut(BaseModel):
    device_id: int
    metric: str
    unit: str = ""
    aggregation: str = "raw"
    samples: list[MetricSample]


class LatestValue(BaseModel):
    device_id: int
    metric: str
    value: float
    unit: str = ""
    status: int = 0
    time: datetime


# --------------------------------------------------------------------------- #
# Alert rules
# --------------------------------------------------------------------------- #


class AlertRuleBase(BaseModel):
    name: str
    scope_type: ScopeType = "global"
    scope_ref: str | None = None
    metric: str
    operator: Operator
    threshold: float
    for_seconds: int = Field(default=0, ge=0, le=3600)
    severity: SeverityT = "warning"
    throttle_seconds: int = Field(default=900, ge=0, le=86400)
    enabled: bool = True


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    scope_type: ScopeType | None = None
    scope_ref: str | None = None
    metric: str | None = None
    operator: Operator | None = None
    threshold: float | None = None
    for_seconds: int | None = Field(default=None, ge=0, le=3600)
    severity: SeverityT | None = None
    throttle_seconds: int | None = Field(default=None, ge=0, le=86400)
    enabled: bool | None = None


class AlertRuleOut(AlertRuleBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


# --------------------------------------------------------------------------- #
# Alerts
# --------------------------------------------------------------------------- #


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int | None
    device_id: int
    metric: str
    severity: SeverityT
    state: Literal["firing", "acked", "resolved"]
    value: float
    message: str
    started_at: datetime
    ended_at: datetime | None
    acked_by: int | None
    acked_at: datetime | None
    ack_comment: str | None
    resolved_by: int | None
    resolved_at: datetime | None
    resolve_comment: str | None
    snoozed_until: datetime | None = None


class AckRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


class ResolveRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)


# --------------------------------------------------------------------------- #
# Settings / SMTP
# --------------------------------------------------------------------------- #


class SmtpSettingsIn(BaseModel):
    host: str | None = None
    port: int = 587
    user: str | None = None
    password: str | None = None  # write-only; stored encrypted
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = "rackmon@localhost"
    recipients: list[str] = Field(default_factory=list)


class SmtpSettingsOut(BaseModel):
    host: str | None = None
    port: int = 587
    user: str | None = None
    has_password: bool = False
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = "rackmon@localhost"
    recipients: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Audit / overview
# --------------------------------------------------------------------------- #


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_id: int | None
    actor_email: str | None = None
    action: str
    target_type: str
    target_id: str | None
    ip: str | None
    created_at: datetime


class OverviewOut(BaseModel):
    devices_total: int
    status_counts: dict[str, int]
    firing_alerts: int
    hottest: list[DeviceStatusOut]
    avg_temperature: float | None
    max_temperature: float | None
    # Para que la interfaz pueda avisar de que esta instalación está MUDA.
    # Dos formas de estarlo, y las dos se han dado de verdad: sin reglas de
    # alerta el motor no puede disparar nada, y sin ningún canal configurado un
    # disparo solo deja una línea en un log que no lee nadie. En ambos casos el
    # panel pinta tarjetas rojas y parece que todo funciona.
    alert_rules_active: int = 0
    notification_channels: int = 0
    # La demo pública no tiene a quién notificar por diseño, así que el aviso de
    # "instalación muda" allí no informa de nada: solo asusta a quien llega desde
    # la web a ver el producto por primera vez.
    demo_mode: bool = False
