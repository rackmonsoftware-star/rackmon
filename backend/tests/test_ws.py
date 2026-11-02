import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.security import create_access_token


def test_ws_rejects_without_token(client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/stream"):
            pass


def test_ws_rejects_bad_token(client: TestClient):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/stream?token=not-valid"):
            pass


def test_ws_connect_and_handshake(client: TestClient):
    token = create_access_token(1, "admin")
    with client.websocket_connect(
        f"/api/v1/stream?token={token}&topics=alerts,device.1.temp_cpu"
    ) as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert "alerts" in msg["topics"]


def test_ws_rejects_unknown_user(client: TestClient):
    # A validly-signed token whose subject is not a real, active user must be
    # rejected (a disabled/deleted account cannot keep streaming).
    token = create_access_token(999999, "admin")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/stream?token={token}"):
            pass
