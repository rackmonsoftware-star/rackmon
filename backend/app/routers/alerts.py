"""Alert management endpoints (RF-37, RF-38)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, record_audit, require_operator
from ..models import Alert, AlertState, User
from ..schemas import AckRequest, AlertOut, ResolveRequest

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def _get_alert(db: Session, alert_id: int) -> Alert:
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    return alert


@router.get("", response_model=list[AlertOut])
def list_alerts(
    state: str | None = Query(default=None, description="firing|acked|resolved"),
    device_id: int | None = Query(default=None),
    severity: str | None = Query(default=None),
    active: bool | None = Query(default=None, description="shortcut: not resolved"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AlertOut]:
    stmt = select(Alert).order_by(Alert.started_at.desc()).limit(limit)
    if state:
        stmt = stmt.where(Alert.state == state)
    if active:
        stmt = stmt.where(Alert.state != AlertState.resolved.value)
    if device_id is not None:
        stmt = stmt.where(Alert.device_id == device_id)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    return [AlertOut.model_validate(a) for a in db.scalars(stmt).all()]


@router.get("/history", response_model=list[AlertOut])
def alert_history(
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    severity: str | None = Query(default=None),
    device_id: int | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[AlertOut]:
    stmt = select(Alert).order_by(Alert.started_at.desc()).limit(limit)
    if frm:
        stmt = stmt.where(Alert.started_at >= frm)
    if to:
        stmt = stmt.where(Alert.started_at <= to)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if device_id is not None:
        stmt = stmt.where(Alert.device_id == device_id)
    return [AlertOut.model_validate(a) for a in db.scalars(stmt).all()]


@router.get("/correlations")
def alert_correlations(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    """Group currently-active (non-resolved) alerts by rack so related alerts
    surface as a single incident instead of a wall of separate notifications."""
    from ..models import Device

    active = db.scalars(
        select(Alert).where(Alert.state != AlertState.resolved.value)
        .order_by(Alert.started_at)
    ).all()
    rack_of = {d.id: d.rack for d in db.scalars(select(Device)).all()}

    groups: dict[str, list[Alert]] = {}
    for a in active:
        rack = rack_of.get(a.device_id) or "unracked"
        groups.setdefault(rack, []).append(a)

    def _ser(a: Alert) -> dict:
        return {"id": a.id, "device_id": a.device_id, "metric": a.metric,
                "severity": a.severity, "state": a.state,
                "started_at": a.started_at, "message": a.message}

    correlations = [
        {
            "rack": rack,
            "count": len(items),
            "severity": "critical" if any(i.severity == "critical" for i in items) else items[0].severity,
            "alerts": [_ser(i) for i in items],
        }
        for rack, items in sorted(groups.items())
        if len(items) >= 2  # a correlation implies more than one related alert
    ]
    singletons = sum(1 for items in groups.values() if len(items) == 1)
    return {"correlations": correlations, "grouped_incidents": len(correlations),
            "singletons": singletons}


@router.get("/{alert_id}", response_model=AlertOut)
def get_alert(alert_id: int, db: Session = Depends(get_db),
              _: User = Depends(get_current_user)) -> AlertOut:
    return AlertOut.model_validate(_get_alert(db, alert_id))


@router.post("/{alert_id}/ack", response_model=AlertOut)
def ack_alert(
    alert_id: int, payload: AckRequest, request: Request,
    db: Session = Depends(get_db), user: User = Depends(require_operator),
) -> AlertOut:
    alert = _get_alert(db, alert_id)
    if alert.state == AlertState.resolved.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already resolved")
    alert.state = AlertState.acked.value
    alert.acked_by = user.id
    alert.acked_at = datetime.now(timezone.utc)
    alert.ack_comment = payload.comment
    record_audit(db, actor_id=user.id, action="alert.ack", target_type="alert",
                 target_id=alert.id, after={"comment": payload.comment}, request=request)
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(
    alert_id: int, payload: ResolveRequest, request: Request,
    db: Session = Depends(get_db), user: User = Depends(require_operator),
) -> AlertOut:
    alert = _get_alert(db, alert_id)
    if alert.state == AlertState.resolved.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already resolved")
    now = datetime.now(timezone.utc)
    alert.state = AlertState.resolved.value
    alert.ended_at = now
    alert.resolved_by = user.id
    alert.resolved_at = now
    alert.resolve_comment = payload.comment
    record_audit(db, actor_id=user.id, action="alert.resolve", target_type="alert",
                 target_id=alert.id, after={"comment": payload.comment}, request=request)
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.post("/{alert_id}/snooze", response_model=AlertOut)
def snooze_alert(
    alert_id: int, request: Request,
    minutes: int = Query(default=60, ge=1, le=10080),
    db: Session = Depends(get_db), user: User = Depends(require_operator),
) -> AlertOut:
    """Temporarily suppress escalation/notification for a single alert."""
    alert = _get_alert(db, alert_id)
    if alert.state == AlertState.resolved.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Alert already resolved")
    alert.snoozed_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    record_audit(db, actor_id=user.id, action="alert.snooze", target_type="alert",
                 target_id=alert.id, after={"minutes": minutes}, request=request)
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)


@router.delete("/{alert_id}/snooze", response_model=AlertOut)
def unsnooze_alert(alert_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_operator)) -> AlertOut:
    alert = _get_alert(db, alert_id)
    alert.snoozed_until = None
    record_audit(db, actor_id=user.id, action="alert.unsnooze", target_type="alert",
                 target_id=alert.id, request=request)
    db.commit()
    db.refresh(alert)
    return AlertOut.model_validate(alert)
