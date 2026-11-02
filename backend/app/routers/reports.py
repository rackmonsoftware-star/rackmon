"""Reporting endpoints (RF-46): ad-hoc report over a date range + device set."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User, ensure_aware
from ..services import reports, sla

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _parse_ids(device_ids: str | None) -> list[int] | None:
    if not device_ids:
        return None
    return [int(x) for x in device_ids.split(",") if x.strip().isdigit()]


@router.get("/adhoc")
def adhoc_report(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    device_ids: str | None = Query(default=None, description="comma-separated device ids"),
    fmt: str = Query(default="pdf", pattern="^(pdf|json|csv)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    end = ensure_aware(to) or datetime.now(timezone.utc)
    start = ensure_aware(from_) or (end - timedelta(days=7))
    ids = _parse_ids(device_ids)
    if device_ids and not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "device_ids contained no valid ids")

    report = reports.compute_report(db, start, end, ids)
    stamp = end.strftime("%Y%m%d")

    if fmt == "json":
        return report

    if fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["device", "samples", "avg_temp", "max_temp", "availability_pct", "pct_over_warn", "pct_over_crit"])
        for d in report["per_device"]:
            w.writerow([d["name"], d["samples"], d["avg_temp"], d["max_temp"],
                        d["availability_pct"], d["pct_over_warn"], d["pct_over_crit"]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="rackmon_report_{stamp}.csv"'},
        )

    pdf = reports.render_pdf(report)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="rackmon_report_{stamp}.pdf"'},
    )


@router.get("/sla")
def sla_report(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    device_ids: str | None = Query(default=None, description="comma-separated device ids"),
    target: float = Query(default=99.9, ge=0, le=100, description="SLA target %"),
    fmt: str = Query(default="pdf", pattern="^(pdf|json|csv)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):

    end = ensure_aware(to) or datetime.now(timezone.utc)
    start = ensure_aware(from_) or (end - timedelta(days=30))
    ids = _parse_ids(device_ids)
    if device_ids and not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "device_ids contained no valid ids")
    try:
        report = sla.compute_sla_report(db, start, end, ids, target_pct=target)
    except ValueError as exc:
        # Un periodo invertido o enteramente en el futuro. Antes se contestaba
        # con un informe de 100 % y cero incidencias, que parece una respuesta
        # buena y no lo es.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    stamp = end.strftime("%Y%m%d")

    if fmt == "json":
        return report
    if fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["device", "availability_pct", "downtime_minutes", "incidents", "mttr_minutes", "sla_met"])
        for d in report["per_device"]:
            w.writerow([d["name"], d["availability_pct"], d["downtime_minutes"],
                        d["incidents"], d["mttr_minutes"], d["sla_met"]])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="rackmon_sla_{stamp}.csv"'},
        )

    pdf = sla.render_sla_pdf(report)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="rackmon_sla_{stamp}.pdf"'},
    )
