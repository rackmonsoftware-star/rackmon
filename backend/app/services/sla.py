"""Informes de disponibilidad y cumplimiento de SLA.

Unlike the ad-hoc thermal report (whose "availability" is a data-completeness
estimate), this derives real availability from **downtime**: the union of the
intervals during which a device had a firing *critical* alert, clipped to the
report window. Availability = (window - downtime) / window. Also reports the
incident count, mean-time-to-resolve (MTTR), and compliance against an SLA
target so an operator (or an MSP) can hand a client a defensible uptime report.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, AlertState, Device, ensure_aware
from .reports import _f, _lat1, _table  # reuse the PDF table helpers


def _merged_downtime_seconds(intervals: list[tuple[datetime, datetime]]) -> float:
    """Total seconds covered by a set of (start, end) intervals, merging any
    overlaps so concurrent alerts are not double-counted."""
    if not intervals:
        return 0.0
    intervals = sorted(intervals, key=lambda iv: iv[0])
    total = 0.0
    cur_s, cur_e = intervals[0]
    for s, e in intervals[1:]:
        if s <= cur_e:
            cur_e = max(cur_e, e)
        else:
            total += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
    total += (cur_e - cur_s).total_seconds()
    return total


def compute_sla_report(
    db: Session,
    start: datetime,
    end: datetime,
    device_ids: list[int] | None = None,
    target_pct: float = 99.9,
) -> dict:
    start = ensure_aware(start)
    end = ensure_aware(end)
    now = datetime.now(timezone.utc)
    # El futuro no se puede medir. Pedir "del 1 al 31" un día 14 daba una ventana
    # de 31 días con la indisponibilidad de 14: los 17 días que todavía no han
    # pasado entraban en el cálculo como tiempo en servicio, así que un equipo
    # caído desde el día 1 salía con un 54 % en vez de un 0 %. Este informe lo
    # firma un proveedor y se lo entrega a su cliente; el número tiene que
    # aguantar que lo miren.
    if end > now:
        end = now
    if end <= start:
        # Ventana vacía o invertida. Antes `max(1.0, negativo)` la dejaba en un
        # segundo y el informe salía con un 100 % de disponibilidad y cero
        # incidencias, que es la respuesta más tranquilizadora posible a una
        # pregunta mal hecha.
        raise ValueError("el fin del periodo debe ser posterior al inicio")
    window_s = (end - start).total_seconds()

    devq = select(Device)
    if device_ids:
        devq = devq.where(Device.id.in_(device_ids))
    devices = db.scalars(devq).all()
    ids = [d.id for d in devices]

    per: dict[int, dict] = {
        d.id: {"intervals": [], "incidents": 0, "resolve_secs": []} for d in devices
    }

    # Critical alerts that could overlap the window (started before it ends).
    aq = select(Alert).where(Alert.severity == "critical", Alert.started_at <= end)
    if ids:
        aq = aq.where(Alert.device_id.in_(ids))
    for a in db.scalars(aq).all():
        pd = per.get(a.device_id)
        if pd is None:
            continue
        s0 = ensure_aware(a.started_at)
        # A still-firing alert runs to "now"; a resolved one to its ended_at.
        e0 = ensure_aware(a.ended_at) or now
        clip_s, clip_e = max(s0, start), min(e0, end)
        if clip_e <= clip_s:
            continue  # no overlap inside the window
        pd["intervals"].append((clip_s, clip_e))
        pd["incidents"] += 1
        if a.state == AlertState.resolved.value and a.ended_at is not None:
            pd["resolve_secs"].append((ensure_aware(a.ended_at) - s0).total_seconds())

    rows = []
    for d in devices:
        pd = per[d.id]
        downtime = _merged_downtime_seconds(pd["intervals"])
        availability = max(0.0, min(100.0, 100.0 * (window_s - downtime) / window_s))
        mttr = (sum(pd["resolve_secs"]) / len(pd["resolve_secs"])) if pd["resolve_secs"] else None
        # Se compara contra el número REDONDEADO, que es el que se publica. Con
        # el valor sin redondear, un equipo al 99,8996 % salía impreso como
        # "99.9 %" junto a un "MISS" contra un objetivo del 99,9 %: el cliente
        # que lee el PDF ve dos cosas que se contradicen y deja de fiarse del
        # resto del informe.
        publicada = round(availability, 3)
        rows.append({
            "device_id": d.id,
            "name": d.name,
            "availability_pct": publicada,
            "downtime_minutes": round(downtime / 60.0, 1),
            "incidents": pd["incidents"],
            "mttr_minutes": round(mttr / 60.0, 1) if mttr is not None else None,
            "sla_met": publicada >= target_pct,
        })
    rows.sort(key=lambda r: r["availability_pct"])  # worst first

    overall = round(sum(r["availability_pct"] for r in rows) / len(rows), 3) if rows else 100.0
    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "target_pct": target_pct,
        "window_minutes": round(window_s / 60.0, 1),
        "overall_availability_pct": overall,
        "device_count": len(rows),
        "devices_meeting_sla": sum(1 for r in rows if r["sla_met"]),
        "total_incidents": sum(r["incidents"] for r in rows),
        "per_device": rows,
    }


def render_sla_pdf(report: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "RackMon - SLA / Availability Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    p = report["period"]
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, f"Period: {p['from']}  ->  {p['to']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"SLA target: {report['target_pct']}%    "
                   f"Devices meeting SLA: {report['devices_meeting_sla']}/{report['device_count']}    "
                   f"Overall availability: {report['overall_availability_pct']}%",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Per-device availability", new_x="LMARGIN", new_y="NEXT")
    _table(
        pdf,
        headers=["Device", "Availability %", "Downtime (min)", "Incidents", "MTTR (min)", "SLA"],
        widths=[54, 30, 30, 24, 26, 18],
        rows=[
            [_lat1(d["name"]), _f(d["availability_pct"]), _f(d["downtime_minutes"]),
             _f(d["incidents"]), _f(d["mttr_minutes"]), "OK" if d["sla_met"] else "MISS"]
            for d in report["per_device"]
        ],
    )

    out = pdf.output()
    return bytes(out) if not isinstance(out, (bytes, bytearray)) else bytes(out)
