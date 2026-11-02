"""ORM models.

PostgreSQL holds configuration, users, alerts and audit; the ``metric_points``
table is the time-series store. On TimescaleDB it becomes a hypertable with
continuous aggregates (see deploy/timescale/init.sql); on SQLite it is a plain
indexed table so the whole stack runs with no external services.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_aware(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC.

    PostgreSQL ``timestamptz`` round-trips aware datetimes, but SQLite returns
    naive ones. Normalizing on read lets the same comparison code run on both.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


class Role(str, enum.Enum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class AlertState(str, enum.Enum):
    firing = "firing"
    acked = "acked"
    resolved = "resolved"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


# Metric status codes stored alongside each point.
STATUS_OK = 0
STATUS_WARN = 1
STATUS_CRIT = 2
STATUS_MISSING = 3


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=Role.viewer.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped on password change / admin reset to revoke all previously-issued
    # access & refresh tokens (they carry the version they were minted with).
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    snmp_version: Mapped[str] = mapped_column(String(8), default="2c", nullable=False)  # 1|2c|3
    snmp_community_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted at rest
    snmpv3_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted SNMPv3 creds JSON
    snmp_port: Mapped[int] = mapped_column(Integer, default=161, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Lightweight rack topology (full DC->room->rack tables are a Phase-2 item).
    rack: Mapped[str | None] = mapped_column(String(128), nullable=True)
    position_u: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_u: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    maintenance_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    metrics: Mapped[list["MetricCatalog"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    @property
    def in_maintenance(self) -> bool:
        until = ensure_aware(self.maintenance_until)
        return until is not None and until > utcnow()


class MetricCatalog(Base):
    __tablename__ = "metrics_catalog"
    __table_args__ = (UniqueConstraint("device_id", "name", name="uq_metric_device_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. temp_cpu
    label: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    oid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    # Lo que devuelve el aparato no siempre es la magnitud real: iDRAC da décimas
    # de grado (275 = 27,5 °C) y APC décimas de amperio. El valor crudo se
    # multiplica por esto antes de guardarlo, así que todo lo que sale de la base
    # de datos —gráficas, alertas, informes— ya habla en la unidad de `unit`.
    # Nullable a propósito: al actualizar, la columna se añade sin valor en las
    # filas que ya existen, y el código trata NULL y 0 como 1.
    scale: Mapped[float | None] = mapped_column(Float, default=1.0, nullable=True)
    poll_interval_s: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    device: Mapped[Device] = relationship(back_populates="metrics")


class MetricPoint(Base):
    """Time-series store (hypertable on TimescaleDB)."""

    __tablename__ = "metric_points"
    __table_args__ = (
        Index("ix_points_device_metric_time", "device_id", "metric_id", "time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_id: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=STATUS_OK, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), default="global", nullable=False)  # device|tag|global
    scope_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # device id or tag
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    operator: Mapped[str] = mapped_column(String(4), nullable=False)  # > < >= <= == !=
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    for_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default=Severity.warning.value, nullable=False)
    throttle_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_state", "state"),
        Index("ix_alerts_device", "device_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id"), nullable=True)
    device_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default=AlertState.firing.value, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolve_comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AlertNotification(Base):
    __tablename__ = "alert_notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="sent", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ua: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class ApiKey(Base):
    """Long-lived programmatic credential (RF-48). Only the hash is stored."""
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Annotation(Base):
    """A timestamped note on a device timeline (e.g. 'replaced fan here')."""
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True, nullable=False)
    metric: Mapped[str | None] = mapped_column(String(64), nullable=True)  # null = whole device
    text: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
