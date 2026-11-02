"""Discovery endpoints: scan a network range and import found hosts (RF, §3.1)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import encrypt
from ..database import get_db
from ..deps import record_audit, require_operator
from ..models import Device, MetricCatalog, User
from ..services import discovery

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


class ScanIn(BaseModel):
    target: str = Field(description="CIDR, 'a.b.c.x-y' range, or a single IP")
    community: str = "public"
    snmp_version: str = "2c"


class DiscoveredHost(BaseModel):
    ip: str
    sysname: str | None = None
    vendor: str | None = None
    already_known: bool = False


class ImportItem(BaseModel):
    ip: str
    name: str | None = None
    snmp_version: Literal["1", "2c", "3"] = "2c"
    community: str = "public"
    rack: str | None = None
    tags: list[str] = Field(default_factory=list)
    # El escaneo YA deduce el fabricante del sysDescr y lo devuelve en
    # DiscoveredHost, pero hasta la 1.2.3 se perdía aquí: el equipo se creaba sin
    # fabricante y, por tanto, con un catálogo que no era el suyo.
    vendor: str | None = None


class ImportIn(BaseModel):
    devices: list[ImportItem]


class ImportResult(BaseModel):
    created: list[int]
    skipped: list[str]


@router.post("/scan", response_model=list[DiscoveredHost])
def scan(payload: ScanIn, db: Session = Depends(get_db),
         _: User = Depends(require_operator)) -> list[DiscoveredHost]:
    try:
        found = discovery.scan(payload.target, payload.community, payload.snmp_version)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    known = {ip for (ip,) in db.execute(select(Device.ip)).all()}
    return [DiscoveredHost(already_known=(h["ip"] in known), **h) for h in found]


@router.post("/import", response_model=ImportResult)
def import_devices(payload: ImportIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_operator)) -> ImportResult:
    from ..services.templates import catalogo_por_defecto

    known = {ip for (ip,) in db.execute(select(Device.ip)).all()}

    created: list[int] = []
    skipped: list[str] = []
    for item in payload.devices:
        if item.ip in known:
            skipped.append(item.ip)
            continue
        device = Device(
            name=item.name or item.ip, ip=item.ip, snmp_version=item.snmp_version,
            snmp_community_enc=encrypt(item.community), rack=item.rack, tags=item.tags,
            vendor=item.vendor, created_by=user.id,
        )
        db.add(device)
        db.flush()
        # Cada equipo con el catálogo de SU fabricante. Importar cuarenta equipos
        # de cinco marcas y darles a todos el de un switch Cisco dejaba la mayoría
        # creados, enchufados y mudos, sin un error que lo explicara.
        for name, label, unit, oid, escala, interval in catalogo_por_defecto(item.vendor):
            db.add(MetricCatalog(device_id=device.id, name=name, label=label,
                                 unit=unit, oid=oid, scale=escala,
                                 poll_interval_s=interval))
        known.add(item.ip)
        created.append(device.id)

    record_audit(db, actor_id=user.id, action="discovery.import", target_type="device",
                 target_id=None, after={"count": len(created)}, request=request)
    db.commit()
    return ImportResult(created=created, skipped=skipped)
