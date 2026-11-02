"""System endpoints: health, Prometheus metrics, dashboard overview."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..config import APP_VERSION, get_settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Alert, AlertState, Device, Setting, User
from ..schemas import OverviewOut
from ..services import licensing, updates
from ..services.collector import es_de_entrada
from .devices import _firing_counts, _firing_severity, compute_status, elevate_status

router = APIRouter(tags=["system"])

DEFAULT_BRANDING = {"product_name": "RackMon", "accent": "#22D3EE", "logo_url": None}

_START = time.monotonic()
_metrics_bearer = HTTPBearer(auto_error=False)


def require_metrics_access(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_metrics_bearer),
    db: Session = Depends(get_db),
) -> None:
    """Guard for GET /metrics: accept the configured metrics token, or fall back
    to normal principal auth (JWT / API key). Never unauthenticated."""
    token = get_settings().metrics_token
    if (
        token
        and creds is not None
        and creds.scheme.lower() == "bearer"
        and secrets.compare_digest(creds.credentials, token)
    ):
        return
    # No (matching) metrics token -> require a normal authenticated principal.
    get_current_user(request, creds, db)  # raises 401 if not authenticated


# HEAD además de GET. FastAPI, a diferencia de Starlette, NO añade HEAD solo
# por declarar un GET, así que RackMon devolvía 405 a cualquier HEAD — y /health
# es justo el endpoint al que un cliente apunta su monitor de disponibilidad.
# Uptime Kuma, UptimeRobot, Pingdom y los check_http de siempre usan HEAD por
# defecto: veían "caído" de forma permanente un RackMon perfectamente sano.
@router.api_route("/health", methods=["GET", "HEAD"])
def health(db: Session = Depends(get_db)) -> dict:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "database": "up" if db_ok else "down",
        "uptime_seconds": round(time.monotonic() - _START, 1),
    }


@router.get("/metrics")
def prometheus_metrics(_: None = Depends(require_metrics_access)) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/branding", tags=["system"])
def branding(db: Session = Depends(get_db)) -> dict:
    """Effective UI branding. Unauthenticated (the login page needs it).

    Hasta la 1.3.0 la marca blanca pedía licencia de pago. Ya no: si has puesto
    un nombre o un color, se usan; si no, los de RackMon."""
    row = db.get(Setting, "branding")
    cfg = row.value if row and isinstance(row.value, dict) else {}
    return {
        "product_name": str(cfg.get("product_name") or DEFAULT_BRANDING["product_name"]),
        "accent": str(cfg.get("accent") or DEFAULT_BRANDING["accent"]),
        "logo_url": cfg.get("logo_url") or None,
    }


@router.get("/api/v1/license", tags=["system"])
def license_info(_: User = Depends(get_current_user)) -> dict:
    """La edición y lo que trae. Desde la 1.3.0 siempre es la misma y lo trae todo.

    Se mantiene porque la interfaz la consulta y porque una instalación antigua que
    actualice no debe encontrarse un 500 donde antes había una pantalla."""
    lic = licensing.get_license()
    return {
        "edition": lic.edition,
        "licensee": lic.licensee,
        "valid": lic.valid,
        "features": sorted(lic.features),
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
        # Cuántos días quedan. Hasta ahora la fecha se exponía pero nadie la
        # miraba: una licencia de un año se apagaba sin un solo aviso previo y el
        # cliente perdía la página de estado, los informes de SLA y la marca
        # blanca de un día para otro, sin saber por qué. Lo único que pasaba era
        # una línea en el log del servidor, que nadie lee.
        "days_left": (
            (lic.expires_at - datetime.now(timezone.utc)).days
            if lic.expires_at is not None
            else None
        ),
        "max_devices": lic.max_devices,
    }


@router.get("/api/v1/update-status", tags=["system"])
def update_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> dict:
    """Version / update-availability + optional vendor announcement.

    Opt-in and privacy-preserving: when the ``updates`` feature is disabled this
    only echoes the running version. Never raises on network/parse errors."""
    return updates.get_update_status(db)


def _reglas_activas(db: Session) -> int:
    """Cuántas reglas de alerta hay encendidas. Cero significa que el motor de
    alertas no puede disparar nada, por caliente que esté la sala."""
    from ..models import AlertRule

    return db.scalar(
        select(func.count()).select_from(AlertRule).where(AlertRule.enabled.is_(True))
    ) or 0


def _canales_configurados(db: Session) -> int:
    """Canales de notificación REALES, sin contar la consola.

    La consola siempre está y siempre dice "enviado", así que una alerta puede
    quedar registrada como notificada sin que haya salido nada de la máquina.
    """
    from ..services import notifier

    n = 0
    try:
        smtp = notifier._smtp_config(db)
        if smtp.get("host") and (smtp.get("recipients") or []):
            n += 1
        ch = notifier._channels_config(db)
        for clave in ("webhook_url", "slack_webhook_url", "teams_webhook_url"):
            if ch.get(clave):
                n += 1
        if ch.get("telegram_token") and ch.get("telegram_chat_id"):
            n += 1
    except Exception:  # pragma: no cover - nunca debe tumbar el resumen
        return n
    return n


@router.get("/api/v1/overview", response_model=OverviewOut, tags=["dashboard"])
def overview(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> OverviewOut:
    devices = db.scalars(select(Device)).all()
    firing = _firing_counts(db)
    sev = _firing_severity(db)

    status_counts = {"ok": 0, "warning": 0, "critical": 0, "nodata": 0, "maintenance": 0}
    statuses = []
    temps: list[float] = []
    for d in devices:
        s = compute_status(d)
        s.firing_alerts = firing.get(d.id, 0)
        s.status = elevate_status(s.status, sev.get(d.id))
        status_counts[s.status] = status_counts.get(s.status, 0) + 1
        if s.temperature is not None:
            temps.append(s.temperature)
        statuses.append(s)

    # La 1.2.2 separó entrada y componente en las alertas, en el estado y en los
    # informes, pero esta pantalla se quedó fuera: seguía metiendo en la misma
    # media los 22 °C de aire de una PDU y los 70 °C de una CPU. Esa media no
    # significa nada, y el ranking de "más calientes" lo encabezaba siempre
    # cualquier equipo con sensor de CPU, tuviera la sala fría o ardiendo.
    #
    # Se mide la ENTRADA, que es lo que habla de la sala. Solo si NINGÚN equipo
    # tiene sensor de entrada se cae a lo que haya, para no dejar la pantalla en
    # blanco en una instalación que aún no tiene sensores de aire.
    de_entrada = [s for s in statuses if es_de_entrada(s.temperature_metric or "")]
    con_temp = [s for s in statuses if s.temperature is not None]

    # La MEDIA y la MÁXIMA hablan de la sala, así que salen del aire de entrada.
    # Si ningún equipo tiene sonda de aire, se cae a lo que haya para no dejar la
    # pantalla en blanco.
    representativos = de_entrada if de_entrada else con_temp
    temps = [s.temperature for s in representativos if s.temperature is not None]

    # El RANKING, en cambio, los incluye a TODOS. Antes bastaba con que UN equipo
    # tuviera sonda de aire para que los otros 108 desaparecieran de la única
    # lista que la gente mira para saber qué está caliente: el panel llegaba a
    # decir "crítico: 1" y "máxima 24 °C" a la vez, porque el crítico era un
    # servidor sin sonda de aire y no salía por ningún lado. Cada fila lleva su
    # temperature_metric, así que la interfaz la pinta en la escala que le toca.
    #
    # Se ordena por ESTADO primero: una CPU a 75 °C (aviso) pesa más que una
    # entrada a 24 °C (normal), aunque el número sea más grande. Dentro del mismo
    # estado manda la temperatura.
    _peso = {"critical": 3, "warning": 2, "maintenance": 1}
    hottest = sorted(
        con_temp,
        key=lambda s: (_peso.get(s.status, 0), s.temperature),
        reverse=True,
    )[:10]

    firing_total = db.scalar(
        select(func.count()).select_from(Alert).where(Alert.state != AlertState.resolved.value)
    ) or 0

    return OverviewOut(
        devices_total=len(devices),
        status_counts=status_counts,
        firing_alerts=int(firing_total),
        hottest=hottest,
        avg_temperature=round(sum(temps) / len(temps), 2) if temps else None,
        max_temperature=round(max(temps), 2) if temps else None,
        alert_rules_active=_reglas_activas(db),
        notification_channels=_canales_configurados(db),
        demo_mode=get_settings().demo_mode,
    )
