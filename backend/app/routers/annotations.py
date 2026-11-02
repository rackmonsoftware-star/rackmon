"""Annotation endpoints (Fase 3): timestamped notes on device timelines."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, record_audit, require_operator
from ..models import Annotation, Device, User

router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])


class AnnotationIn(BaseModel):
    device_id: int
    metric: str | None = None
    text: str
    at: datetime | None = None


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    device_id: int
    metric: str | None
    text: str
    at: datetime
    created_by: int | None
    created_at: datetime


@router.get("", response_model=list[AnnotationOut])
def list_annotations(
    device_id: int = Query(...),
    metric: str | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = select(Annotation).where(Annotation.device_id == device_id)
    if metric:
        q = q.where(Annotation.metric == metric)
    if from_:
        q = q.where(Annotation.at >= from_)
    if to:
        q = q.where(Annotation.at <= to)
    return list(db.scalars(q.order_by(Annotation.at)).all())


@router.post("", response_model=AnnotationOut, status_code=status.HTTP_201_CREATED)
def create_annotation(payload: AnnotationIn, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_operator)):
    if db.get(Device, payload.device_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    ann = Annotation(
        device_id=payload.device_id, metric=payload.metric, text=payload.text,
        at=payload.at or datetime.now(timezone.utc), created_by=user.id,
    )
    db.add(ann)
    db.flush()
    record_audit(db, actor_id=user.id, action="annotation.create", target_type="annotation",
                 target_id=ann.id, request=request)
    db.commit()
    db.refresh(ann)
    return ann


class AnnotationUpdate(BaseModel):
    text: str


@router.patch("/{ann_id}", response_model=AnnotationOut)
def update_annotation(ann_id: int, payload: AnnotationUpdate, request: Request,
                      db: Session = Depends(get_db), user: User = Depends(require_operator)):
    ann = db.get(Annotation, ann_id)
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    ann.text = payload.text
    record_audit(db, actor_id=user.id, action="annotation.update", target_type="annotation",
                 target_id=ann_id, request=request)
    db.commit()
    db.refresh(ann)
    return ann


@router.delete("/{ann_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(ann_id: int, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require_operator)) -> Response:
    ann = db.get(Annotation, ann_id)
    if ann is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Annotation not found")
    db.delete(ann)
    record_audit(db, actor_id=user.id, action="annotation.delete", target_type="annotation",
                 target_id=ann_id, request=request)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
