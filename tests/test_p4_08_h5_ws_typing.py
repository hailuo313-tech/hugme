from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.realtime import h5_manager, router


def test_p4_08_h5_ws_receives_typing_status(monkeypatch):
    monkeypatch.setattr("api.realtime.CLIENT_RECV_TIMEOUT_SECONDS", 0.001)
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        with client.websocket_connect(
            "/ws/h5/chat?user_id=h5-user-1&conversation_id=conv-1&trace_id=trace-p4-08"
        ) as ws:
            ready = ws.receive_json()
            assert ready["type"] == "connection.ready"
            assert ready["user_id"] == "h5-user-1"
            assert ready["conversation_id"] == "conv-1"

            assert "h5-user-1" in h5_manager.active_connections
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

            client.portal.call(h5_manager.send_typing_status, "h5-user-1", True)
            typing = ws.receive_json()
            assert typing["type"] == "typing.status"
            assert typing["user_id"] == "h5-user-1"
            assert typing["is_typing"] is True

    assert "h5-user-1" not in h5_manager.active_connections
