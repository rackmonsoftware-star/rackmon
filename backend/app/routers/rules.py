"""Alert rule CRUD (RF-28..RF-30)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, record_audit, require_operator
from ..models import Alert, AlertRule, Device, User
from ..schemas import AlertRuleCreate, AlertRuleOut, AlertRuleUpdate

router = APIRouter(prefix="/api/v1/rules", tags=["rules"])


def _validate_scope(db: Session, scope_type: str, scope_ref: str | None) -> None:
    if scope_type == "device":
        if not scope_ref or not scope_ref.isdigit() or not db.get(Device, int(scope_ref)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "scope_ref must be a valid device id for device scope",
            )
    if scope_type == "tag" and not scope_ref:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "scope_ref (tag) required for tag scope"
        )


@router.get("", response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db),
               _: User = Depends(get_current_user)) -> list[AlertRuleOut]:
    rules = db.scalars(select(AlertRule).order_by(AlertRule.name)).all()
    return [AlertRuleOut.model_validate(r) for r in rules]


@router.post("", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(payload: AlertRuleCreate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_operator)) -> AlertRuleOut:
    _validate_scope(db, payload.scope_type, payload.scope_ref)
    rule = AlertRule(**payload.model_dump())
    db.add(rule)
    record_audit(db, actor_id=user.id, action="rule.create", target_type="rule",
                 after={"name": rule.name}, request=request)
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.get("/{rule_id}", response_model=AlertRuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db),
             _: User = Depends(get_current_user)) -> AlertRuleOut:
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return AlertRuleOut.model_validate(rule)


@router.patch("/{rule_id}", response_model=AlertRuleOut)
def update_rule(rule_id: int, payload: AlertRuleUpdate, request: Request,
                db: Session = Depends(get_db), user: User = Depends(require_operator)) -> AlertRuleOut:
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    data = payload.model_dump(exclude_unset=True)
    scope_type = data.get("scope_type", rule.scope_type)
    scope_ref = data.get("scope_ref", rule.scope_ref)
    _validate_scope(db, scope_type, scope_ref)
    for field, value in data.items():
        setattr(rule, field, value)
    record_audit(db, actor_id=user.id, action="rule.update", target_type="rule",
                 target_id=rule.id, request=request)
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_operator)) -> Response:
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    record_audit(db, actor_id=user.id, action="rule.delete", target_type="rule",
                 target_id=rule.id, before={"name": rule.name}, request=request)
    # Detach the alerts this rule produced (nullable FK) so the delete can't fail
    # on a foreign-key constraint; the alert history is preserved.
    db.execute(sa_update(Alert).where(Alert.rule_id == rule_id).values(rule_id=None))
    db.delete(rule)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
