"""Device management endpoints (RF-01, RF-05, RF-08)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from ..crypto import encrypt
from ..database import get_db
from ..deps import get_current_user, record_audit, require_operator
from ..models import (
    Alert,
    AlertNotification,
    AlertState,
    Annotation,
    Device,
    MetricCatalog,
    MetricPoint,
    User,
    ensure_aware,
)
from ..schemas import (
    DeviceCreate,
    DeviceOut,
    DeviceStatusOut,
    DeviceUpdate,
    LatestValue,
    MaintenanceRequest,
    MetricCatalogOut,
)
from ..services.collector import METRICAS_DE_ENTRADA, es_de_entrada
from ..services.poller import latest

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


def to_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id, name=device.name, hostname=device.hostname, ip=device.ip,
        snmp_version=device.snmp_version, snmp_port=device.snmp_port,
        vendor=device.vendor, model=device.model, rack=device.rack,
        position_u=device.position_u, size_u=device.size_u, tags=device.tags or [],
        enabled=device.enabled, created_at=device.created_at,
        has_community=device.snmp_community_enc is not None,
        has_snmpv3=device.snmpv3_enc is not None,
        in_maintenance=device.in_maintenance,
        metrics=[MetricCatalogOut.model_validate(m) for m in device.metrics],
    )


def compute_status(device: Device) -> DeviceStatusOut:
    if device.in_maintenance:
        state = "maintenance"
    else:
        state = "nodata"
    temp = None
    last_seen = None
    values = latest.for_device(device.id)
    # Solo cuentan las métricas que SIGUEN en el catálogo del equipo.
    #
    # `latest` es una caché en memoria y no se entera de que alguien borre una
    # métrica: el operador veía un temp_inlet mal configurado marcando 275 °C,
    # lo borraba del catálogo para quitarse el problema, y el equipo seguía en
    # rojo crítico con 275 °C indefinidamente — hasta reiniciar el proceso. La
    # única salida era un reinicio, y nada en pantalla lo decía.
    # Sin condición: un catálogo vacío significa que no se sondea nada, así que
    # NINGÚN valor cacheado debe contar. Poner aquí un "si hay métricas" dejaba
    # pasar justo el caso que esto venía a arreglar: borrar la única métrica.
    nombres_vigentes = {m.name for m in device.metrics}
    values = [v for v in values if v["metric"] in nombres_vigentes]
    worst = 0
    # La temperatura que representa a un dispositivo es la del AIRE QUE ENTRA,
    # no la de su CPU. Es lo que dicen nuestras propias guías y es lo único que
    # habla de la sala: una CPU a 70 °C bajo carga es normal y no dice nada del
    # rack. Antes esto miraba SOLO temp_cpu, así que el mapa térmico y las medias
    # del panel eran temperaturas de CPU — y un aparato sin temp_cpu (un PDU de
    # APC, por ejemplo) aparecía sin temperatura ninguna.
    por_nombre = {v["metric"]: v["value"] for v in values}
    for v in values:
        if v["time"] and (last_seen is None or v["time"] > last_seen):
            last_seen = v["time"]
        worst = max(worst, v["status"])
    # Se guarda también DE QUÉ métrica salió. La interfaz lo necesita para pintar
    # el color: 32 °C de aire de entrada es crítico y 32 °C de CPU es un equipo en
    # reposo. Sin esto el mapa térmico tiene que adivinar, y adivina mal.
    temp_metrica = None
    for preferida in (*METRICAS_DE_ENTRADA, "temp_cpu"):
        if preferida in por_nombre:
            temp = por_nombre[preferida]
            temp_metrica = preferida
            break
    else:
        # Ningún nombre exacto: puede ser una segunda sonda de aire
        # ("temp_inlet_2"), que sigue siendo aire y manda sobre la CPU.
        for nombre, valor in por_nombre.items():
            if es_de_entrada(nombre):
                temp = valor
                temp_metrica = nombre
                break
    if temp is None:
        # Cualquier otra temperatura antes que no enseñar nada.
        for nombre, valor in por_nombre.items():
            if nombre.startswith("temp"):
                temp = valor
                temp_metrica = nombre
                break
    if not device.in_maintenance and values:
        state = {0: "ok", 1: "warning", 2: "critical"}.get(worst, "ok")
        # ...salvo que el dato sea VIEJO. La caché en memoria guarda el último
        # valor para siempre: si un equipo deja de responder, su última lectura
        # se queda ahí y el panel lo sigue pintando en verde. Un equipo que se
        # apagó hace tres días seguía diciendo «24 °C, todo bien», que es la
        # mentira más cómoda que puede contar un monitor.
        #
        # El margen es tres veces el intervalo de sondeo más lento del equipo,
        # con un suelo de 90 s: así un sondeo que se salta un ciclo no lo marca
        # como caído, pero uno que lleva un rato mudo deja de contar como sano.
        if last_seen is not None:
            intervalo = max((m.poll_interval_s or 30) for m in device.metrics) if device.metrics else 30
            margen = max(90.0, intervalo * 3)
            edad = (datetime.now(timezone.utc) - ensure_aware(last_seen)).total_seconds()
            if edad > margen:
                state = "nodata"

    firing = 0  # filled by caller when needed
    return DeviceStatusOut(
        device=to_out(device), status=state, temperature=temp,
        temperature_metric=temp_metrica,
        last_seen=last_seen, firing_alerts=firing,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(
    tag: str | None = Query(default=None),
    rack: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(default=None, description="search name/ip/hostname"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[DeviceOut]:
    stmt = select(Device).order_by(Device.rack, Device.position_u.desc(), Device.name)
    if rack:
        stmt = stmt.where(Device.rack == rack)
    if enabled is not None:
        stmt = stmt.where(Device.enabled.is_(enabled))
    devices = db.scalars(stmt).all()
    if tag:
        devices = [d for d in devices if tag in (d.tags or [])]
    if q:
        needle = q.lower()
        devices = [
            d for d in devices
            if needle in (d.name or "").lower()
            or needle in (d.ip or "").lower()
            or needle in (d.hostname or "").lower()
        ]
    return [to_out(d) for d in devices]


@router.get("/status", response_model=list[DeviceStatusOut])
def devices_status(
    db: Session = Depends(get_db), _: User = Depends(get_current_user)
) -> list[DeviceStatusOut]:
    devices = db.scalars(select(Device)).all()
    firing = _firing_counts(db)
    sev = _firing_severity(db)
    out = []
    for d in devices:
        s = compute_status(d)
        s.firing_alerts = firing.get(d.id, 0)
        s.status = elevate_status(s.status, sev.get(d.id))
        out.append(s)
    out.sort(key=lambda s: (s.device.rack or "", -(s.device.position_u or 0)))
    return out


@router.get("/latest", response_model=list[LatestValue])
def latest_values(
    rack: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[LatestValue]:
    ids = None
    if rack:
        ids = {d.id for d in db.scalars(select(Device).where(Device.rack == rack)).all()}
    out = []
    for v in latest.all():
        if ids is not None and v["device_id"] not in ids:
            continue
        out.append(LatestValue(**v))
    return out


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def create_device(
    payload: DeviceCreate, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> DeviceOut:
    device = Device(
        name=payload.name, hostname=payload.hostname, ip=payload.ip,
        snmp_version=payload.snmp_version, snmp_port=payload.snmp_port,
        snmp_community_enc=encrypt(payload.snmp_community),
        vendor=payload.vendor, model=payload.model, rack=payload.rack,
        position_u=payload.position_u, size_u=payload.size_u,
        tags=payload.tags, enabled=payload.enabled, created_by=user.id,
    )
    if payload.snmpv3:
        from ..services import snmpv3

        # Se valida AQUÍ, al guardarla, y no cuando se intente usar. Una errata
        # en el nombre del protocolo ("sha256" en minúsculas, "SHA-256" con
        # guion) hacía que la sesión saliera sin autenticar y sin cifrar, con la
        # pantalla diciendo authPriv. Que el error salte en la cara de quien lo
        # está escribiendo es la única forma de que se entere.
        try:
            snmpv3.validar(payload.snmpv3)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        device.snmpv3_enc = snmpv3.encode(payload.snmpv3)
    db.add(device)
    db.flush()

    metrics = payload.metrics
    if not metrics:
        # Catálogo de arranque según el fabricante. Antes esto ponía OID de Cisco
        # a cualquier equipo, así que un Dell creado sin métricas no devolvía
        # nada y no había forma de saber por qué.
        from ..services.templates import catalogo_por_defecto

        for name, label, unit, oid, escala, interval in catalogo_por_defecto(device.vendor):
            db.add(MetricCatalog(device_id=device.id, name=name, label=label, unit=unit,
                                 oid=oid, scale=escala, poll_interval_s=interval))
    else:
        seen = set()
        for m in metrics:
            if m.name in seen:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"duplicate metric {m.name}")
            seen.add(m.name)
            db.add(MetricCatalog(device_id=device.id, name=m.name, label=m.label, unit=m.unit,
                                 oid=m.oid, scale=m.scale,
                                 poll_interval_s=m.poll_interval_s, enabled=m.enabled))

    record_audit(db, actor_id=user.id, action="device.create", target_type="device",
                 target_id=device.id, after={"name": device.name, "ip": device.ip},
                 request=request)
    db.commit()
    db.refresh(device)
    return to_out(device)


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)) -> DeviceOut:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    return to_out(device)


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: int, payload: DeviceUpdate, request: Request,
    db: Session = Depends(get_db), user: User = Depends(require_operator),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    before = {"name": device.name, "ip": device.ip, "enabled": device.enabled}

    data = payload.model_dump(exclude_unset=True)
    if "snmp_community" in data:
        community = data.pop("snmp_community")
        device.snmp_community_enc = encrypt(community)
    for field, value in data.items():
        setattr(device, field, value)

    record_audit(db, actor_id=user.id, action="device.update", target_type="device",
                 target_id=device.id, before=before,
                 after={"name": device.name, "ip": device.ip, "enabled": device.enabled},
                 request=request)
    db.commit()
    db.refresh(device)
    return to_out(device)


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(device_id: int, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require_operator)) -> Response:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    record_audit(db, actor_id=user.id, action="device.delete", target_type="device",
                 target_id=device.id, before={"name": device.name}, request=request)
    # Remove all data that references this device so the delete can't fail on a
    # foreign-key constraint (annotations) or leave orphan rows behind (alerts,
    # metric points — these use a bare device_id, not an FK). Metrics cascade via
    # the ORM relationship. Done explicitly here so it works on every backend
    # (SQLite/Postgres) and on existing databases without a schema migration.
    alert_ids = select(Alert.id).where(Alert.device_id == device_id)
    db.execute(sa_delete(AlertNotification).where(AlertNotification.alert_id.in_(alert_ids)))
    db.execute(sa_delete(Alert).where(Alert.device_id == device_id))
    db.execute(sa_delete(MetricPoint).where(MetricPoint.device_id == device_id))
    db.execute(sa_delete(Annotation).where(Annotation.device_id == device_id))
    db.delete(device)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{device_id}/maintenance", response_model=DeviceOut)
def set_maintenance(
    device_id: int, payload: MaintenanceRequest, request: Request,
    db: Session = Depends(get_db), user: User = Depends(require_operator),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    device.maintenance_until = datetime.now(timezone.utc) + timedelta(minutes=payload.minutes)
    record_audit(db, actor_id=user.id, action="device.maintenance", target_type="device",
                 target_id=device.id, after={"until": device.maintenance_until.isoformat()},
                 request=request)
    db.commit()
    db.refresh(device)
    return to_out(device)


@router.delete("/{device_id}/maintenance", response_model=DeviceOut)
def clear_maintenance(
    device_id: int, request: Request, db: Session = Depends(get_db),
    user: User = Depends(require_operator),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    device.maintenance_until = None
    record_audit(db, actor_id=user.id, action="device.maintenance.clear",
                 target_type="device", target_id=device.id, request=request)
    db.commit()
    db.refresh(device)
    return to_out(device)


def _firing_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Alert.device_id).where(Alert.state != AlertState.resolved.value)
    ).all()
    counts: dict[int, int] = {}
    for (device_id,) in rows:
        counts[device_id] = counts.get(device_id, 0) + 1
    return counts


_STATUS_RANK = {"nodata": 0, "ok": 1, "maintenance": 1, "warning": 2, "critical": 3}


def _firing_severity(db: Session) -> dict[int, str]:
    """Worst severity among *active* (non-resolved) alerts, per device id. Used
    to propagate active-alert state into the device's effective status so a
    device with an open alert never shows as green 'Nominal' (a monitoring tool
    must not contradict itself). Uses the same non-resolved set as the Overview
    'active alerts' KPI and the per-device firing count, so badge, count and
    fleet breakdown always agree."""
    rows = db.execute(
        select(Alert.device_id, Alert.severity).where(Alert.state != AlertState.resolved.value)
    ).all()
    out: dict[int, str] = {}
    for device_id, sev in rows:
        cand = sev if sev in ("warning", "critical") else "warning"
        if _STATUS_RANK[cand] > _STATUS_RANK.get(out.get(device_id, "nodata"), 0):
            out[device_id] = cand
    return out


def elevate_status(base: str, alert_severity: str | None) -> str:
    """Raise a temperature-derived status to at least the firing alert's
    severity. Maintenance is left untouched (alerts are suppressed there)."""
    if not alert_severity or base == "maintenance":
        return base
    return alert_severity if _STATUS_RANK.get(alert_severity, 0) > _STATUS_RANK.get(base, 0) else base
