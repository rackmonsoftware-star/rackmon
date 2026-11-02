"""Página de estado pública, sin autenticar.

Un tablero de solo lectura que un proveedor puede enseñar a sus clientes sin
darles cuenta: qué equipos hay, cómo están y, si se quiere, sus temperaturas.

Se sirve ÚNICAMENTE si el administrador la ha encendido a propósito. Mientras
esté apagada responde 404 y no 403, para no anunciarle a un visitante anónimo
que aquí hay una página que existe pero no le dejan ver.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Device, Setting
from .devices import compute_status

router = APIRouter(prefix="/api/v1/public", tags=["public"])

# Worst-first ordering for the board and the overall roll-up.
_RANK = {"critical": 0, "warning": 1, "nodata": 2, "maintenance": 3, "ok": 4}


def _config(db: Session) -> dict:
    row = db.get(Setting, "status_page")
    return row.value if row and isinstance(row.value, dict) else {}


# GET y HEAD: la página de estado pública es, por definición, lo que alguien de
# fuera consulta para saber si esto vive. Ver la nota de system.py:/health.
@router.api_route("/status", methods=["GET", "HEAD"])
def public_status(db: Session = Depends(get_db)) -> dict:
    cfg = _config(db)
    # Apagada = inexistente. Un 404 (y no un 403) para no revelar que está ahí.
    if not cfg.get("enabled"):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Not found")

    show_temps = bool(cfg.get("show_temperatures", True))
    devices = db.scalars(select(Device).where(Device.enabled.is_(True))).all()

    counts = {"ok": 0, "warning": 0, "critical": 0, "nodata": 0, "maintenance": 0}
    items: list[dict] = []
    for d in devices:
        s = compute_status(d)
        counts[s.status] = counts.get(s.status, 0) + 1
        item: dict = {"name": d.name, "status": s.status}
        if show_temps and s.temperature is not None:
            item["temperature"] = s.temperature
        items.append(item)

    if counts["critical"]:
        overall = "critical"
    elif counts["warning"]:
        overall = "warning"
    elif counts["ok"]:
        overall = "ok"
    else:
        overall = "nodata"

    items.sort(key=lambda i: (_RANK.get(i["status"], 9), i["name"]))
    return {
        "title": str(cfg.get("title") or "System status"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "summary": counts,
        "devices": items,
    }
