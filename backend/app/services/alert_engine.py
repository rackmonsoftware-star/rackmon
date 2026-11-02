"""Alert engine.

Evaluates threshold rules against incoming readings and manages the alert
lifecycle: ``firing -> acked (optional) -> resolved``. Implements the parts of
the spec that matter for a trustworthy MVP:

* Persistence windows (``for_seconds``): a condition must hold before firing.
* Deduplication: at most one active alert per (rule, device) — no re-firing.
* Throttled re-notification while still firing (``throttle_seconds``).
* Auto-resolution with a recovery notification when the condition clears.
* Maintenance windows suppress firing (device in maintenance).

Base-line/statistical anomaly conditions and cross-metric correlation are
Phase-4 items; the rule model already carries the fields to grow into them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..metrics_prom import ALERTS_FIRING
from ..models import Alert, AlertRule, AlertState, Device, ensure_aware
from ..services.collector import METRICA_ALCANZABLE, Reading
from . import notifier

log = logging.getLogger("rackmon.alerts")

_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def evaluate_condition(operator: str, value: float, threshold: float) -> bool:
    fn = _OPS.get(operator)
    return bool(fn(value, threshold)) if fn else False


def _mensaje(rule: AlertRule, reading: Reading) -> str:
    """El texto que lee una persona en el correo o en Slack.

    Para una temperatura, "temp_inlet > 32 (actual 40.3)" se entiende solo. Para
    el latido de alcanzabilidad no: "device_reachable < 1.0 (actual 0.0)" obliga
    a quien recibe el aviso a las tres de la mañana a adivinar qué significa.
    """
    if reading.metric_name == METRICA_ALCANZABLE:
        return "Device unreachable: no usable reading in the last poll"
    return (
        f"{reading.metric_name} {rule.operator} {rule.threshold} "
        f"(actual {reading.value:.1f})"
    )


@dataclass
class _Pending:
    """Transient per-(rule, device) state kept in memory between ticks."""
    first_true_at: datetime | None = None
    clear_streak: int = 0
    last_notified_at: datetime | None = None


@dataclass
class AlertEngine:
    # key: (rule_id, device_id)
    _pending: dict[tuple[int, int], _Pending] = field(default_factory=dict)
    resolve_cycles: int = 2  # consecutive clear readings before auto-resolve

    def _rules_for(self, db: Session, device: Device, metric_name: str) -> list[AlertRule]:
        rules = db.scalars(
            select(AlertRule).where(
                AlertRule.enabled.is_(True), AlertRule.metric == metric_name
            )
        ).all()
        out: list[AlertRule] = []
        for r in rules:
            if r.scope_type == "global":
                out.append(r)
            elif r.scope_type == "device" and str(device.id) == str(r.scope_ref):
                out.append(r)
            elif r.scope_type == "tag" and r.scope_ref in (device.tags or []):
                out.append(r)
        return out

    def _active_alert(self, db: Session, rule_id: int, device_id: int) -> Alert | None:
        return db.scalars(
            select(Alert)
            .where(
                Alert.rule_id == rule_id,
                Alert.device_id == device_id,
                Alert.state != AlertState.resolved.value,
            )
            .order_by(Alert.started_at.desc())
        ).first()

    def process(self, db: Session, device: Device, readings: list[Reading]) -> list[Alert]:
        """Evaluate readings for one device. Returns alerts that changed state.

        The caller owns the transaction (commits after). Notifications are
        recorded within the same transaction.
        """
        now = datetime.now(timezone.utc)
        changed: list[Alert] = []

        for reading in readings:
            # A NaN reading means the metric is currently unavailable (poll
            # timeout / decode error), NOT that the alert condition cleared.
            # It carries no information, so it must never fire, resolve, or
            # advance the clear streak — otherwise a transient gap would
            # auto-resolve a live alert and send a false "recovered" alert,
            # hiding a real incident.
            missing = not (reading.value == reading.value)  # NaN != NaN

            for rule in self._rules_for(db, device, reading.metric_name):
                key = (rule.id, device.id)
                pend = self._pending.setdefault(key, _Pending())
                active = self._active_alert(db, rule.id, device.id)

                # Maintenance and missing data suppress evaluation entirely:
                # never fire a new alert and — critically — never resolve an
                # existing one (suppress != resolve). Leave the alert and the
                # hold/clear state untouched so nothing is lost on resume.
                if missing or device.in_maintenance:
                    continue

                if evaluate_condition(rule.operator, reading.value, rule.threshold):
                    pend.clear_streak = 0
                    if pend.first_true_at is None:
                        pend.first_true_at = now
                    held = (now - pend.first_true_at).total_seconds()

                    if active is None and held >= rule.for_seconds:
                        alert = self._fire(db, rule, device, reading, now)
                        pend.last_notified_at = now
                        changed.append(alert)
                    elif active is not None:
                        self._maybe_renotify(db, active, device, pend, rule, now)
                else:
                    pend.first_true_at = None
                    if active is not None:
                        pend.clear_streak += 1
                        if pend.clear_streak >= self.resolve_cycles:
                            self._resolve(db, active, device, reading, now)
                            pend.clear_streak = 0
                            changed.append(active)

        self._refresh_gauge(db)
        return changed

    def _maybe_renotify(self, db: Session, active: Alert, device: Device,
                        pend: _Pending, rule: AlertRule, now: datetime) -> None:
        """Re-notify a still-firing alert at most once per throttle window.

        Acknowledged alerts (a human already owns the incident) and snoozed
        alerts are intentionally left alone — re-notifying them is pure alert
        fatigue and is one of the fastest ways to get users to mute a monitor.
        """
        if rule.throttle_seconds <= 0:
            return
        if active.state != AlertState.firing.value:
            return  # acked/other -> someone is handling it; stay quiet
        snoozed_until = ensure_aware(active.snoozed_until)
        if snoozed_until is not None and snoozed_until > now:
            return  # user asked for silence until then
        # On the first evaluation after a (re)start, pend.last_notified_at is None.
        # Seed the throttle window from `now` (not the alert's started_at) so a
        # long-firing alert doesn't immediately re-notify — a restart storm that
        # spams operators on every deploy.
        if pend.last_notified_at is None:
            pend.last_notified_at = now
            return
        if (now - pend.last_notified_at).total_seconds() >= rule.throttle_seconds:
            self._safe_dispatch(db, active, device)
            pend.last_notified_at = now

    def _fire(self, db: Session, rule: AlertRule, device: Device, reading: Reading,
              now: datetime) -> Alert:
        alert = Alert(
            rule_id=rule.id,
            device_id=device.id,
            metric=reading.metric_name,
            severity=rule.severity,
            state=AlertState.firing.value,
            value=reading.value,
            message=_mensaje(rule, reading),
            started_at=now,
        )
        db.add(alert)
        db.flush()  # assign id for notifications
        log.info("FIRING alert #%s device=%s %s", alert.id, device.id, alert.message)
        self._safe_dispatch(db, alert, device)
        return alert

    def _resolve(self, db: Session, alert: Alert, device: Device, reading: Reading,
                 now: datetime) -> None:
        alert.state = AlertState.resolved.value
        alert.ended_at = now
        # Stamp resolved_at so downstream consumers (history, reports, SLA) see
        # a consistent resolution time; resolved_by stays NULL to mark it as an
        # automatic (system) resolution rather than a human action.
        alert.resolved_at = now
        if not alert.resolve_comment:
            alert.resolve_comment = "Auto-resolved: condition cleared"
        db.flush()
        log.info("RESOLVED alert #%s device=%s", alert.id, device.id)
        # Recovery notification (best-effort).
        self._safe_dispatch(db, alert, device)

    def _safe_dispatch(self, db: Session, alert: Alert, device: Device) -> None:
        """Send an alert transition's notifications without ever letting a
        notifier failure roll back or lose the alert. The alert record is the
        source of truth; delivery is best-effort and logged on failure."""
        try:
            notifier.dispatch(db, alert, device)
        except Exception:  # pragma: no cover - defensive
            log.exception("notifier.dispatch failed for alert #%s", alert.id)

    def _refresh_gauge(self, db: Session) -> None:
        try:
            active_ids = db.scalars(
                select(Alert.id).where(Alert.state != AlertState.resolved.value)
            ).all()
            ALERTS_FIRING.set(len(active_ids))
        except Exception:  # pragma: no cover
            pass

    def reset(self) -> None:
        self._pending.clear()

    def evict_devices(self, valid_device_ids: set[int]) -> None:
        """Drop pending state for devices that no longer exist (avoids a slow leak)."""
        for key in [k for k in self._pending if k[1] not in valid_device_ids]:
            self._pending.pop(key, None)


engine = AlertEngine()
