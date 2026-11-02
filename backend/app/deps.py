"""Reusable FastAPI dependencies: authentication and role checks."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuditLog, Role, User
from .security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    # Alternative auth: a long-lived API key (RF-48) via the X-API-Key header.
    if creds is None or not creds.credentials:
        api_key = request.headers.get("X-API-Key")
        if api_key:
            user = _resolve_api_key(db, api_key)
            if user is None:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
            request.state.user_id = user.id
            return user
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User inactive or missing")
    if payload.get("tv", 0) != (user.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked; sign in again")
    request.state.user_id = user.id
    return user


def _resolve_api_key(db: Session, api_key: str) -> User | None:
    from .models import ApiKey  # local import avoids a cycle at module load
    from .security import hash_api_key

    row = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_api_key(api_key), ApiKey.revoked.is_(False))
    )
    if row is None or row.created_by is None:
        return None
    user = db.get(User, row.created_by)
    if user is None or not user.is_active:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return user


# Role hierarchy: admin > operator > viewer
_RANK = {Role.viewer.value: 0, Role.operator.value: 1, Role.admin.value: 2}


def require_role(minimum: Role) -> Callable[[User], User]:
    threshold = _RANK[minimum.value]

    def _dep(user: User = Depends(get_current_user)) -> User:
        if _RANK.get(user.role, -1) < threshold:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires {minimum.value} role or higher",
            )
        return user

    return _dep


require_viewer = require_role(Role.viewer)
require_operator = require_role(Role.operator)
require_admin = require_role(Role.admin)


def record_audit(
    db: Session,
    *,
    actor_id: int | None,
    action: str,
    target_type: str = "",
    target_id: str | int | None = None,
    before: dict | None = None,
    after: dict | None = None,
    request: Request | None = None,
) -> None:
    """Append an immutable audit entry. Caller commits."""
    ip = None
    ua = None
    if request is not None:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
    entry = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        before=before,
        after=after,
        ip=ip,
        ua=ua,
    )
    db.add(entry)
