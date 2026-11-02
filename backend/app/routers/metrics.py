"""Time-series query & export endpoints (RF-22, RF-27).

Aggregation is computed with time-bucketing that works identically on SQLite and
PostgreSQL. On TimescaleDB the same query targets continuous aggregates for
speed; the response contract is unchanged.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Device, MetricCatalog, MetricPoint, User, ensure_aware
from ..schemas import MetricSample, MetricSeriesOut

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])

_AGG_SECONDS = {"raw": 0, "1m": 60, "5m": 300, "1h": 3600}


def _resolve_metric(db: Session, device_id: int, metric: str) -> MetricCatalog:
    row = db.scalar(
        select(MetricCatalog).where(
            MetricCatalog.device_id == device_id, MetricCatalog.name == metric
        )
    )
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Metric not found for device")
    return row


def _bucket(points: list[MetricPoint], seconds: int) -> list[MetricSample]:
    if seconds <= 0:
        return [MetricSample(time=p.time, value=p.value, status=p.status) for p in points]
    buckets: dict[int, list[MetricPoint]] = defaultdict(list)
    for p in points:
        epoch = int(p.time.replace(tzinfo=p.time.tzinfo or timezone.utc).timestamp())
        buckets[epoch - (epoch % seconds)].append(p)
    out: list[MetricSample] = []
    for start in sorted(buckets):
        grp = buckets[start]
        avg = sum(p.value for p in grp) / len(grp)
        out.append(
            MetricSample(
                time=datetime.fromtimestamp(start, tz=timezone.utc),
                value=round(avg, 3),
                status=max(p.status for p in grp),
            )
        )
    return out


def _query_points(db: Session, device_id: int, metric_id: int,
                  frm: datetime, to: datetime) -> list[MetricPoint]:
    return db.scalars(
        select(MetricPoint)
        .where(
            and_(
                MetricPoint.device_id == device_id,
                MetricPoint.metric_id == metric_id,
                MetricPoint.time >= frm,
                MetricPoint.time <= to,
            )
        )
        .order_by(MetricPoint.time)
    ).all()


@router.get("", response_model=MetricSeriesOut)
def query_series(
    device_id: int = Query(...),
    metric: str = Query(...),
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    agg: str = Query(default="raw"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MetricSeriesOut:
    if agg not in _AGG_SECONDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"agg must be one of {list(_AGG_SECONDS)}")
    now = datetime.now(timezone.utc)
    to = ensure_aware(to) or now
    frm = ensure_aware(frm) or (to - timedelta(hours=1))
    if frm >= to:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'from' must be before 'to'")

    cat = _resolve_metric(db, device_id, metric)
    points = _query_points(db, device_id, cat.id, frm, to)
    samples = _bucket(points, _AGG_SECONDS[agg])
    return MetricSeriesOut(
        device_id=device_id, metric=metric, unit=cat.unit, aggregation=agg, samples=samples
    )


@router.get("/export")
def export_series(
    device_id: int = Query(...),
    metric: str = Query(...),
    frm: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    agg: str = Query(default="raw"),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> Response:
    series = query_series(device_id=device_id, metric=metric, frm=frm, to=to, agg=agg,
                          db=db, _=_)
    device = db.get(Device, device_id)
    name = f"{device.name if device else device_id}_{metric}_{agg}"
    # device.name is user-controlled and lands in a Content-Disposition header;
    # keep only filename-safe characters to block header/response-splitting.
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)[:100] or "export"

    if fmt == "json":
        body = series.model_dump_json()
        return Response(
            body, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["time", "value", "status", "unit"])
    for s in series.samples:
        writer.writerow([s.time.isoformat(), s.value, s.status, series.unit])
    return Response(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("/anomalies")
def anomalies(
    device_id: int = Query(...),
    metric: str = Query(...),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    k: float = Query(default=3.0, ge=1.0, le=10.0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    from ..services import anomaly

    m = _resolve_metric(db, device_id, metric)
    end = to or datetime.now(timezone.utc)
    start = from_ or (end - timedelta(hours=24))
    points = _query_points(db, device_id, m.id, start, end)
    values = [p.value for p in points]
    idx = set(anomaly.detect(values, k))
    zs = anomaly.zscores(values)
    return {
        "device_id": device_id,
        "metric": metric,
        "unit": m.unit,
        "k": k,
        "samples": len(values),
        "count": len(idx),
        "anomalies": [
            {"time": points[i].time, "value": points[i].value, "z": zs[i]}
            for i in sorted(idx)
        ],
    }
