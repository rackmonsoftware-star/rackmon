"""Real-time WebSocket stream (RF-21, RF-50).

Clients authenticate with a short-lived access token (query param, since browser
WebSocket cannot send Authorization headers) and subscribe to topics such as
``device.42.temp_cpu`` or ``alerts``. The connection is fed by the in-process
realtime hub, which the poller and alert engine publish to.
"""
from __future__ import annotations

import asyncio
import logging

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..metrics_prom import WS_CLIENTS
from ..models import User
from ..security import decode_token
from ..services.realtime import hub

log = logging.getLogger("rackmon.ws")
router = APIRouter()


@router.websocket("/api/v1/stream")
async def stream(websocket: WebSocket, token: str = Query(default=""),
                 topics: str = Query(default="")) -> None:
    # Authenticate before accepting. A valid signature is not enough: verify the
    # subject is still a real, active user (a revoked/disabled account with a
    # not-yet-expired token must not keep streaming).
    try:
        payload = decode_token(token, expected_type="access")
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        await websocket.close(code=4401)  # unauthorized
        return
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            await websocket.close(code=4403)  # forbidden: inactive/unknown
            return

    await websocket.accept()
    topic_set = {t.strip() for t in topics.split(",") if t.strip()}
    sub = await hub.subscribe(topic_set)
    WS_CLIENTS.set(hub.client_count)
    await websocket.send_json({"type": "connected", "topics": sorted(topic_set) or ["*"]})

    async def _pump() -> None:
        while True:
            msg = await sub.queue.get()
            await websocket.send_json(msg)

    async def _drain_client() -> None:
        # Read (and ignore) client frames so disconnects are detected promptly.
        while True:
            await websocket.receive_text()

    pump = asyncio.create_task(_pump())
    drain = asyncio.create_task(_drain_client())
    try:
        done, pending = await asyncio.wait(
            {pump, drain}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("ws closed: %s", exc)
    finally:
        pump.cancel()
        drain.cancel()
        await hub.unsubscribe(sub)
        WS_CLIENTS.set(hub.client_count)
