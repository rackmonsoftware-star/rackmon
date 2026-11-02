"""In-app support: forward a user's message to the vendor support desk.

User-initiated only — this is NOT telemetry. The instance forwards the message
server-side (so the browser never talks to the vendor cross-origin, and verified
instance context can be attached). Self-hosters can repoint or disable it via
``RACKMON_SUPPORT_URL``.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Literal

from pydantic import BaseModel, field_validator

from ..config import APP_VERSION, get_settings
from ..deps import get_current_user
from ..models import User
from ..services.licensing import get_license

log = logging.getLogger("rackmon.support")
router = APIRouter(prefix="/api/v1/support", tags=["support"])


class SupportMessage(BaseModel):
    message: str
    email: str | None = None
    # What the user is sending. Lets the vendor triage bug reports ahead of
    # ideas and questions; defaults keep older clients working unchanged.
    kind: Literal["bug", "idea", "question"] = "question"

    @field_validator("message")
    @classmethod
    def _clean_message(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > 5000:
            raise ValueError("message too long (max 5000 characters)")
        return v


def _support_available(settings) -> bool:
    """El canal de soporte existe cuando hay un buzón configurado Y esta instancia
    no es la demo pública.

    En la demo entra cualquiera sin cuenta, así que el formulario de soporte no
    contacta con el proveedor de nadie: es un buzón abierto a internet con nuestra
    dirección al otro lado. El sitio de este formulario es una instalación de
    verdad, donde quien escribe es un usuario real de esa instalación y se sabe
    quién es. Aquí se apaga, y se apaga en el servidor: esconder el botón en la
    interfaz no impediría que alguien llamase al endpoint directamente.
    """
    return bool(settings.support_url) and not settings.demo_mode


@router.get("/config")
def support_config(user: User = Depends(get_current_user)) -> dict:
    """Whether this instance has a support desk configured.

    Self-hosters can unset ``RACKMON_SUPPORT_URL`` (and white-label installs often
    do). Without this, the UI would keep offering a Feedback button that can only
    ever fail, telling the user to "try again" for something that will never work.
    """
    return {"enabled": _support_available(get_settings())}


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def send_support(payload: SupportMessage, user: User = Depends(get_current_user)) -> dict:
    """Forward a support message to the configured vendor desk. Requires auth so
    only real users of the instance can send, and the sender is traceable."""
    settings = get_settings()
    if not _support_available(settings):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Support channel is not configured"
        )

    try:
        edition = getattr(get_license(), "edition", "community")
    except Exception:  # pragma: no cover - licensing must never block support
        edition = "community"

    body = json.dumps(
        {
            "message": payload.message,
            "kind": payload.kind,
            "from_email": (payload.email or getattr(user, "email", "") or "").strip(),
            "user_role": getattr(user, "role", None),
            "version": APP_VERSION,
            "edition": edition,
            "instance_id": settings.instance_id or settings.public_base_url,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        settings.support_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": f"RackMon/{APP_VERSION}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.warning("support forward failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not reach the support desk. Please try again in a moment.",
        )
    return {"ok": True}
