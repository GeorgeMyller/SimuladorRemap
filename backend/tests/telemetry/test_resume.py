"""Reconexão com ``resume_from_seq`` (T166; tel RF-10; EC-04, EC-05; websocket-telemetry 7)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tel_helpers import FakeWebSocket, StubService, raw_event, raw_frame
from ws_helpers import closed_with, is_frame, new_session, recv_until, send, url

from simremap.telemetry.broadcaster import ReplayBuffer, TelemetryStream
from simremap.telemetry.contracts import KnockEventPayload
from simremap.telemetry.ws import TelemetryConnection


def knock(t: float, cylinder: int = 2, run_id: str | None = "r") -> dict[str, Any]:
    payload = KnockEventPayload(
        run_id=run_id,
        cylinder=cylinder,
        knock_class="moderate",
        intensity=0.41,
        intensity_raw=2.1,
        mapo_kpa=210.0,
        theta_onset_deg_atdc=12.0,
        retard_deg=2.0,
        rpm=5012.0,
        p_max_bar=96.4,
        threshold=0.15,
    ).model_dump(mode="json")
    return {"type": "event.knock", "t_sim_s": t, "payload": payload}


def _env(seq: int, t: float) -> dict[str, Any]:
    return {"v": 1, "type": "event.knock", "seq": seq, "t_sim_s": t, "payload": {}}


def test_replay_buffer_limits_512_or_10s() -> None:
    buf = ReplayBuffer()
    for i in range(600):
        buf.append(_env(i, i * 0.001))
    assert len(buf.items) == 512 and buf.oldest_seq == 88 and buf.evicted_max_seq == 87
    buf = ReplayBuffer()
    for i in range(30):
        buf.append(_env(i, float(i)))
    assert buf.oldest_seq == 19  # só os últimos 10 s simulados
    buf.observe(100.0)  # frames avançam o tempo
    assert buf.items == type(buf.items)()


def test_resume_plans() -> None:
    buf = ReplayBuffer()
    for i in range(5):
        buf.append(_env(10 + i, i * 0.1))
    plan = buf.resume(11, 20)
    assert [e["seq"] for e in plan.events] == [12, 13, 14]
    assert plan.gap_oldest_seq is None and not plan.invalid
    assert buf.resume(99, 20).invalid
    for i in range(600):
        buf.append(_env(100 + i, 1.0 + i * 0.001))
    gap = buf.resume(11, 800)
    assert gap.gap_oldest_seq == buf.oldest_seq and gap.events  # o ao vivo continua


async def test_preamble_snapshot_then_replay_with_original_seq() -> None:
    stream = TelemetryStream("s")
    stream.publish(raw_event("run.state", 1.0, run_id="r", state="running", phase="pull"))
    last_seen = stream.publish(raw_frame(50, 1.0))["seq"]  # type: ignore[index]
    first = stream.publish(knock(1.5))
    second = stream.publish(knock(2.9, cylinder=3))
    stream.publish(raw_frame(150, 3.0))
    ws = FakeWebSocket()
    conn = TelemetryConnection(ws, StubService(), "s", stream)  # type: ignore[arg-type]
    task = asyncio.create_task(conn.run(last_seen))
    await asyncio.sleep(0.01)
    stream.publish(raw_frame(151, 3.02))
    await asyncio.sleep(0.01)
    kinds = [(m["type"], m["seq"]) for m in ws.sent]
    assert kinds[0][0] == "run.state" and kinds[0][1] > second["seq"]  # type: ignore[index]
    assert ws.sent[0]["payload"]["state"] == "running"
    assert kinds[1:3] == [("event.knock", first["seq"]), ("event.knock", second["seq"])]  # type: ignore[index]
    assert kinds[3][0] == "telemetry.frame"  # depois do replay, só frames novos
    assert ws.sent[3]["payload"]["frame_index"] == 151
    task.cancel()


def test_resume_e2e_with_real_session(e2e_app: FastAPI, e2e_client: TestClient) -> None:
    sid = new_session(e2e_client)
    stream = e2e_app.state.dyno_stream_hub.get(sid)
    assert isinstance(stream, TelemetryStream)
    with e2e_client.websocket_connect(url(sid)) as ws:
        ws.receive_json()
        send(ws, "control.throttle", throttle_pct=0)
        frame, _ = recv_until(ws, is_frame)
        last = frame["seq"]
    # Queda: 2 event.knock emitidos enquanto o cliente está desligado.
    portal = e2e_client.portal
    assert portal is not None
    t = stream.replay_buffer.latest_t
    a = portal.call(stream.publish, knock(t + 0.01))
    b = portal.call(stream.publish, knock(t + 0.02, cylinder=4))
    assert a is not None and b is not None
    with e2e_client.websocket_connect(url(sid, resume_from_seq=last)) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "run.state" and snapshot["seq"] > b["seq"]
        replay = [ws.receive_json(), ws.receive_json()]
        assert [(m["type"], m["seq"]) for m in replay] == [
            ("event.knock", a["seq"]),
            ("event.knock", b["seq"]),
        ]
        assert replay[1]["payload"]["cylinder"] == 4
        nxt, _ = recv_until(ws, lambda m: m["type"] != "event.knock")
        assert nxt["type"] == "telemetry.frame" and nxt["seq"] > snapshot["seq"]
        # Subscrição não é restaurada: canais padrão.
        assert set(nxt["payload"]["channels"]) == {
            "rpm",
            "map_kpa",
            "lambda",
            "torque_nm",
            "power_kw",
        }
    # Gap: mais de 512 eventos depois do seq pedido.
    t = stream.replay_buffer.latest_t
    for i in range(600):
        portal.call(stream.publish, knock(t + 0.03 + i * 1e-4, cylinder=1 + i % 4))
    with e2e_client.websocket_connect(url(sid, resume_from_seq=last)) as ws:
        assert ws.receive_json()["type"] == "run.state"
        gap = ws.receive_json()
        assert gap["type"] == "error" and gap["payload"]["code"] == "WS_RESUME_GAP"
        assert gap["payload"]["oldest_available_seq"] == stream.replay_buffer.oldest_seq
        recv_until(ws, is_frame)  # o fluxo ao vivo continua
    # resume_from_seq no futuro: WS_RESUME_INVALID e conexão nova.
    with e2e_client.websocket_connect(url(sid, resume_from_seq=10**9)) as ws:
        assert ws.receive_json()["type"] == "run.state"
        invalid = ws.receive_json()
        assert invalid["payload"]["code"] == "WS_RESUME_INVALID"
        frame, seen = recv_until(ws, is_frame)
        assert all(m["type"] != "event.knock" for m in seen)
    assert e2e_client.delete(f"/api/v1/sessions/{sid}").status_code == 204
    with e2e_client.websocket_connect(url(sid)) as ws:
        exc = closed_with(ws)
    assert exc.code == 4404
