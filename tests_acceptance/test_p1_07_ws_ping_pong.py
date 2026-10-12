from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.realtime import router


def test_p1_07_ws_ping_pong(monkeypatch):
    monkeypatch.setattr("api.realtime.CLIENT_RECV_TIMEOUT_SECONDS", 0.001)
    app = FastAPI()
    app.include_router(router)

    with TestClient(app) as client:
        with client.websocket_connect("/ws?client_id=p1-07&trace_id=trace-p1-07") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "connection.ready"
            assert ready["client_id"] == "p1-07"

            ws.send_json({"type": "ping"})
            pong = ws.receive_json()

            assert pong["type"] == "pong"
            assert pong["trace_id"] == "trace-p1-07"
            assert pong["client_id"] == "p1-07"
