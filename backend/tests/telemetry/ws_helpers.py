"""Auxiliares dos testes ponta a ponta do WebSocket (``TestClient``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from simremap.telemetry.contracts import WsEnvelope

SHORT = {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}
Message = dict[str, Any]


def new_session(client: TestClient) -> str:
    resp = client.post("/api/v1/sessions", json={"vehicle_id": "hatch-20t-gdi", "seed": 3})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["session_id"])


def url(session_id: str, **query: Any) -> str:
    q = "&".join(f"{k}={v}" for k, v in query.items())
    return f"/ws/v1/sessions/{session_id}/telemetry" + (f"?{q}" if q else "")


def send(ws: WebSocketTestSession, kind: str, **payload: Any) -> None:
    ws.send_json({"v": 1, "type": kind, "payload": payload})


def recv_until(
    ws: WebSocketTestSession, pred: Callable[[Message], bool], limit: int = 3000
) -> tuple[Message, list[Message]]:
    seen: list[Message] = []
    for _ in range(limit):
        message: Message = ws.receive_json()
        WsEnvelope.model_validate(message)
        seen.append(message)
        if pred(message):
            return message, seen
    raise AssertionError("mensagem esperada não chegou")


def is_frame(m: Message) -> bool:
    return bool(m["type"] == "telemetry.frame")


def is_error(code: str) -> Callable[[Message], bool]:
    return lambda m: m["type"] == "error" and m["payload"]["code"] == code


def closed_with(ws: WebSocketTestSession) -> WebSocketDisconnect:
    with pytest.raises(WebSocketDisconnect) as info:
        for _ in range(5000):
            ws.receive_json()
    return info.value
