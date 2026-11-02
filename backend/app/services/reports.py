"""Reporting: availability, SLA (time over threshold), and PDF rendering.

Covers the spec's reporting requirements (RF-45/46/47): an ad-hoc report over a
date range and device selection, with alerts-by-severity, hottest devices,
per-device uptime estimate, and time-over-threshold (SLA).

Temperature status is evaluated at poll time and stored on each point
(0=ok, 1=warn, 2=crit), so "time over threshold" is derived directly from the
stored status rather than re-checking thresholds here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Alert, Device, MetricCatalog, MetricPoint, Setting, ensure_aware
from .collector import es_de_entrada


def compute_report(
    db: Session,
    start: datetime,
    end: datetime,
    device_ids: list[int] | None = None,
) -> dict:
    range_seconds = max(1.0, (end - start).total_seconds())

    # Agregación por dispositivo sobre los puntos de temperatura del periodo.
    #
    # Antes esto metía en el mismo saco TODAS las métricas "temp%": la CPU a
    # 70 °C y la entrada a 22 °C salían promediadas en un único "avg_temp" que
    # no significaba nada, y el "max_temp" era siempre la CPU, así que el
    # ranking de equipos más calientes ordenaba por CPU. En un informe de SLA,
    # que es lo que el cliente enseña a su jefe, eso es peor que no darlo.
    #
    # Se mide la ENTRADA, que es lo que habla de la sala. Solo si un equipo no
    # tiene sensor de entrada se cae a sus otras temperaturas, para no dejarlo
    # fuera del informe sin decir nada.
    def _agregar(filtro_nombre):
        q = (
            select(
                MetricCatalog.device_id.label("device_id"),
                func.count(MetricPoint.id).label("n"),
                func.avg(MetricPoint.value).label("avg_v"),
                func.max(MetricPoint.value).label("max_v"),
                func.sum(case((MetricPoint.status >= 1, 1), else_=0)).label("warn_n"),
                func.sum(case((MetricPoint.status >= 2, 1), else_=0)).label("crit_n"),
                func.min(MetricCatalog.poll_interval_s).label("interval"),
            )
            .join(MetricCatalog, MetricCatalog.id == MetricPoint.metric_id)
            .where(filtro_nombre)
            .where(MetricPoint.time >= start, MetricPoint.time <= end)
            .group_by(MetricCatalog.device_id)
        )
        if device_ids:
            q = q.where(MetricCatalog.device_id.in_(device_ids))
        return db.execute(q).all()

    # Qué nombres de este catálogo son AIRE, decidido por familia y no por
    # igualdad: un equipo con dos sondas las llama "temp_inlet" y "temp_inlet_2",
    # y el segundo nombre no entraba en la lista, así que su pasillo acababa
    # promediado con las CPU. Se resuelve en Python —que es donde vive la regla—
    # y la consulta recibe la lista exacta, sin LIKE que se pase de listo.
    nombres_temp = [
        n for (n,) in db.execute(
            select(MetricCatalog.name).where(MetricCatalog.name.like("temp%")).distinct()
        ).all()
    ]
    nombres_entrada = [n for n in nombres_temp if es_de_entrada(n)]
    nombres_otros = [n for n in nombres_temp if not es_de_entrada(n)]

    rows = _agregar(MetricCatalog.name.in_(nombres_entrada)) if nombres_entrada else []
    con_entrada = {r.device_id for r in rows}
    otras = [
        r for r in (_agregar(MetricCatalog.name.in_(nombres_otros)) if nombres_otros else [])
        if r.device_id not in con_entrada
    ]
    rows = list(rows) + otras

    # De qué tipo de sensor sale la cifra de cada fila. Sin esto, el informe —que
    # es el documento que el cliente le enseña a su jefe— pintaba la CPU con la
    # escala del aire: un servidor sin sonda de aire cuya CPU promedia 55 °C,
    # perfectamente normal, salía en rojo de crítico en la misma fila que un
    # "0 % sobre aviso" y un "0 % sobre crítico". El documento se contradecía solo.
    tipo_por_dispositivo = {r.device_id: "entrada" for r in rows if r.device_id in con_entrada}
    for r in otras:
        tipo_por_dispositivo[r.device_id] = "componente"

    names = {
        d.id: d.name
        for d in db.scalars(select(Device)).all()
    }

    per_device = []
    for r in rows:
        n = r.n or 0
        interval = r.interval or 30
        expected = max(1, int(range_seconds / max(1, interval)))
        availability = min(100.0, round(100.0 * n / expected, 1)) if n else 0.0
        per_device.append({
            "device_id": r.device_id,
            "name": names.get(r.device_id, f"#{r.device_id}"),
            "samples": n,
            "avg_temp": round(r.avg_v, 1) if r.avg_v is not None else None,
            "max_temp": round(r.max_v, 1) if r.max_v is not None else None,
            "availability_pct": availability,
            "pct_over_warn": round(100.0 * (r.warn_n or 0) / n, 1) if n else 0.0,
            "pct_over_crit": round(100.0 * (r.crit_n or 0) / n, 1) if n else 0.0,
            "sensor": tipo_por_dispositivo.get(r.device_id, "entrada"),
        })
    per_device.sort(key=lambda d: (d["max_temp"] or -1), reverse=True)

    # Alerts by severity started in range.
    sev_rows = db.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.started_at >= start, Alert.started_at <= end)
        .group_by(Alert.severity)
    ).all()
    alerts_by_severity = {"info": 0, "warning": 0, "critical": 0}
    for sev, count in sev_rows:
        alerts_by_severity[sev] = count

    return {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "alerts_by_severity": alerts_by_severity,
        "hottest": per_device[:10],
        "per_device": per_device,
        "device_count": len(per_device),
    }


def render_pdf(report: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "RackMon - Thermal Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    p = report["period"]
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, f"Period: {p['from']}  ->  {p['to']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Devices reported: {report['device_count']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Alerts by severity
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Alerts by severity", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    a = report["alerts_by_severity"]
    pdf.cell(0, 6, f"Critical: {a['critical']}    Warning: {a['warning']}    Info: {a['info']}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Hottest devices
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Hottest devices", new_x="LMARGIN", new_y="NEXT")
    _table(
        pdf,
        headers=["Device", "Avg C", "Max C", "% > warn", "% > crit", "Uptime %"],
        widths=[60, 24, 24, 26, 26, 26],
        rows=[
            [d["name"], _f(d["avg_temp"]), _f(d["max_temp"]),
             _f(d["pct_over_warn"]), _f(d["pct_over_crit"]), _f(d["availability_pct"])]
            for d in report["hottest"]
        ],
    )

    out = pdf.output()
    return bytes(out) if not isinstance(out, (bytes, bytearray)) else bytes(out)


def _f(v) -> str:
    return "-" if v is None else f"{v}"


def _lat1(text: str) -> str:
    """Core PDF fonts are Latin-1 only; drop-in-safe any device names/values."""
    return text.encode("latin-1", "replace").decode("latin-1")


def _table(pdf, headers: list[str], widths: list[int], rows: list[list[str]]) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(230, 234, 238)
    for h, w in zip(headers, widths):
        pdf.cell(w, 7, h, border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    if not rows:
        pdf.cell(sum(widths), 7, "No data in range", border=1, new_x="LMARGIN", new_y="NEXT")
        return
    for row in rows:
        for value, w in zip(row, widths):
            pdf.cell(w, 6, _lat1(str(value))[:28], border=1)
        pdf.ln()


# --------------------------------------------------------------------------- #
# Scheduled weekly report (RF-45): compiled PDF emailed on a cadence.
# --------------------------------------------------------------------------- #
_LAST_SENT_KEY = "report_last_sent"


def _report_schedule(db: Session) -> dict:
    s = get_settings()
    cfg = {"enabled": s.report_weekly_enabled,
           "recipients": list(s.report_weekly_recipients)}
    row = db.get(Setting, "report_schedule")
    if row and row.value:
        cfg.update({k: v for k, v in row.value.items() if v is not None})
    return cfg


def send_weekly_report(db: Session) -> bool:
    """Build the last-7-days report and email it as a PDF. Returns True if sent."""
    from . import notifier

    cfg = notifier._smtp_config(db)
    sched = _report_schedule(db)
    recipients = sched.get("recipients") or cfg.get("recipients") or []
    if not cfg.get("host") or not recipients:
        return False

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=7)
    pdf = render_pdf(compute_report(db, start, end))
    subject = f"[RackMon] Weekly thermal report {start.date()} to {end.date()}"
    body = "Attached is the RackMon weekly thermal report (last 7 days)."
    notifier._send_email(cfg, subject, body, recipients,
                         attachments=[("rackmon_weekly_report.pdf", pdf, "application/pdf")])
    return True


def maybe_send_weekly_report(db: Session, now: datetime | None = None) -> bool:
    """Send the weekly report if enabled and at least 7 days have elapsed."""
    if not _report_schedule(db).get("enabled"):
        return False
    now = now or datetime.now(timezone.utc)
    row = db.get(Setting, _LAST_SENT_KEY)
    last = None
    if row and row.value and row.value.get("at"):
        try:
            last = ensure_aware(datetime.fromisoformat(row.value["at"]))
        except ValueError:
            last = None
    if last and (now - last).days < 7:
        return False
    if not send_weekly_report(db):
        return False
    if row:
        row.value = {"at": now.isoformat()}
    else:
        db.add(Setting(key=_LAST_SENT_KEY, value={"at": now.isoformat()}))
    db.commit()
    return True
