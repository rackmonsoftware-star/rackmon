"""Device template endpoints (Fase 2): list templates, create device from one."""
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
from ..schemas import DeviceOut
from ..services import templates

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


class TemplateApplyIn(BaseModel):
    template: str
    name: str
    ip: str
    community: str = "public"
    snmp_version: Literal["1", "2c", "3"] = "2c"
    rack: str | None = None
    position_u: int | None = Field(default=None, ge=1, le=60)
    tags: list[str] = Field(default_factory=list)


@router.get("")
def list_templates(_: User = Depends(require_operator)) -> list[dict]:
    return templates.list_templates()


@router.post("/apply", response_model=DeviceOut, status_code=status.HTTP_201_CREATED)
def apply_template(payload: TemplateApplyIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require_operator)):
    from ..routers.devices import to_out

    tpl = templates.get(payload.template)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    if db.scalar(select(Device).where(Device.ip == payload.ip)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A device with this IP already exists")

    device = Device(
        name=payload.name, ip=payload.ip, snmp_version=payload.snmp_version,
        snmp_community_enc=encrypt(payload.community), vendor=tpl["vendor"],
        rack=payload.rack, position_u=payload.position_u, tags=payload.tags,
        created_by=user.id,
    )
    db.add(device)
    db.flush()
    for name, label, unit, oid, scale, interval in tpl["metrics"]:
        db.add(MetricCatalog(device_id=device.id, name=name, label=label, unit=unit,
                             oid=oid, scale=scale, poll_interval_s=interval))
    record_audit(db, actor_id=user.id, action="device.from_template", target_type="device",
                 target_id=device.id, after={"template": payload.template, "ip": payload.ip},
                 request=request)
    db.commit()
    db.refresh(device)
    return to_out(device)
