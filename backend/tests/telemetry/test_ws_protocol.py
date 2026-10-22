"""Protocolo do WebSocket ponta a ponta com sessão real do dyno (T165, T431; tel RF-01, RF-02,
RF-05, RF-07, RF-22, RF-24; EC-02, EC-06, EC-15, EC-18; websocket-telemetry 1, 4 e 8).

App completa (``create_app``), worker ``process`` com o hatch calibrado e o
``TelemetrySampler`` instalado pelo lifespan da telemetria; cliente ``TestClient``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ws_helpers import SHORT, closed_with, is_error, is_frame, new_session, recv_until, send, url

from simremap.telemetry.contracts import DEFAULT_CHANNELS, TelemetryFrame
from simremap.telemetry.sampler import SAMPLER_SPEC


def test_sampler_installed_and_handshake_rejections(
    e2e_app: FastAPI, e2e_client: TestClient
) -> None:
    assert e2e_app.state.dyno_service.task_options["sampler"] == SAMPLER_SPEC
    with e2e_client.websocket_connect(url("0" * 32)) as ws:
        exc = closed_with(ws)
    assert (exc.code, exc.reason) == (4404, "SESSION_NOT_FOUND")
    sid = new_session(e2e_client)
    with e2e_client.websocket_connect(url(sid), headers={"origin": "http://evil.example"}) as ws:
        exc = closed_with(ws)
    assert (exc.code, exc.reason) == (4403, "WS_ORIGIN_FORBIDDEN")
    sockets = [
        e2e_client.websocket_connect(url(sid), headers={"origin": "http://localhost:5173"})
        for _ in range(4)
    ]
    opened = [s.__enter__() for s in sockets]
    try:
        for ws in opened:
            assert ws.receive_json()["type"] == "run.state"
        assert e2e_app.state.telemetry_service.connections(sid) == 4
        with e2e_client.websocket_connect(url(sid)) as fifth:
            exc = closed_with(fifth)
        assert (exc.code, exc.reason) == (4429, "WS_TOO_MANY_CONNECTIONS")
    finally:
        for s in sockets:
            s.__exit__(None, None, None)


def test_default_channels_subscribe_and_errors(e2e_client: TestClient) -> None:
    sid = new_session(e2e_client)
    with e2e_client.websocket_connect(url(sid)) as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "run.state" and snapshot["payload"]["state"] == "idle"
        assert snapshot["seq"] == 0
        send(ws, "control.throttle", throttle_pct=0)  # tira a sessão da espera determinística
        frame, _ = recv_until(ws, is_frame)
        assert set(frame["payload"]["channels"]) == set(DEFAULT_CHANNELS)
        assert frame["payload"]["window_ticks"] == 20
        assert frame["payload"]["run_id"] is None
        TelemetryFrame.model_validate(frame["payload"])
        send(ws, "control.subscribe", channels=["rpm", "torque_nm"])
        frame, _ = recv_until(ws, is_frame)
        frame, _ = recv_until(ws, is_frame)
        assert set(frame["payload"]["channels"]) == {"rpm", "torque_nm"}
        # Canal desconhecido: erro com a lista inválida, válidos ativos.
        send(ws, "control.subscribe", channels=["rpm", "egt_c_cyl9", "boost_bar"])
        err, seen = recv_until(ws, is_error("WS_UNKNOWN_CHANNEL"))
        assert err["payload"]["detail"] == "egt_c_cyl9" and err["payload"]["fatal"] is False
        before = [m["seq"] for m in seen]
        frame, _ = recv_until(ws, is_frame)
        assert set(frame["payload"]["channels"]) == {"rpm", "boost_bar"}
        assert frame["seq"] > err["seq"] > max(before[:-1], default=-1)
        send(ws, "control.subscribe", channels=["rpm"], fps=25)
        recv_until(ws, is_error("WS_FPS_OUT_OF_RANGE"))
        send(ws, "control.subscribe", channels=["rpm"], pressure_trace={"cylinder": 9})
        recv_until(ws, is_error("WS_CYLINDER_OUT_OF_RANGE"))
        # fps 60 para a sessão: janelas de 16/17 ticks.
        send(ws, "control.subscribe", channels=["rpm", "throttle_pct"], fps=60)
        for _ in range(4):
            recv_until(ws, is_frame)
        frame, _ = recv_until(ws, is_frame)
        assert frame["payload"]["window_ticks"] in (16, 17)
        # control.throttle em idle muda o throttle_pct dos frames seguintes.
        start = frame["payload"]["channels"]["throttle_pct"]
        send(ws, "control.throttle", throttle_pct=50)
        frame, _ = recv_until(
            ws, lambda m: is_frame(m) and m["payload"]["channels"]["throttle_pct"] > start + 1
        )
        send(ws, "control.ping", nonce="a1")
        send(ws, "control.throttle", throttle_pct=150)
        recv_until(ws, is_error("WS_MESSAGE_INVALID"))


def test_throttle_locked_during_run_and_invalid_messages(e2e_client: TestClient) -> None:
    sid = new_session(e2e_client)
    with e2e_client.websocket_connect(url(sid)) as ws:
        ws.receive_json()
        resp = e2e_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
        assert resp.status_code == 202
        recv_until(ws, lambda m: m["type"] == "run.state" and m["payload"]["state"] == "arming")
        send(ws, "control.throttle", throttle_pct=50)
        err, _ = recv_until(ws, is_error("THROTTLE_LOCKED_BY_RUN"))
        assert err["payload"]["fatal"] is False
        ws.send_text("{nao é json")
        recv_until(ws, is_error("WS_MESSAGE_INVALID"))
        send(ws, "control.desconhecido")
        recv_until(ws, is_error("WS_MESSAGE_INVALID"))
        ws.send_text('{"v": 1, "type": "control.ping", "payload": {"x": "' + "a" * 17000 + '"}}')
        recv_until(ws, is_error("WS_MESSAGE_INVALID"))
        frame, _ = recv_until(ws, is_frame)  # a conexão continua
        assert frame["payload"]["run_id"] == resp.json()["run_id"]
        for _ in range(18):
            ws.send_text("lixo")
        fatal, _ = recv_until(ws, is_error("WS_RATE_LIMITED"))
        assert fatal["payload"]["fatal"] is True
        exc = closed_with(ws)
    assert (exc.code, exc.reason) == (1008, "WS_RATE_LIMITED")


def test_idle_timeout_ping_and_session_delete(e2e_app: FastAPI, e2e_client: TestClient) -> None:
    e2e_app.state.telemetry_idle_timeout_s = 0.6
    sid = new_session(e2e_client)
    with e2e_client.websocket_connect(url(sid)) as ws:
        ws.receive_json()
        exc = closed_with(ws)
    assert (exc.code, exc.reason) == (4408, "WS_IDLE_TIMEOUT")
    e2e_app.state.telemetry_idle_timeout_s = 30.0
    with e2e_client.websocket_connect(url(sid)) as ws:
        ws.receive_json()
        send(ws, "control.throttle", throttle_pct=0)
        recv_until(ws, is_frame)
        resp = e2e_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
        recv_until(ws, lambda m: m["type"] == "run.state" and m["payload"]["state"] == "arming")
        assert e2e_client.delete(f"/api/v1/sessions/{sid}").status_code == 204
        final, _ = recv_until(
            ws, lambda m: m["type"] == "run.state" and m["payload"]["state"] == "aborted"
        )
        assert final["payload"]["abort_reason"] == "session_closed"
        assert final["payload"]["run_id"] == resp.json()["run_id"]
        exc = closed_with(ws)
    assert exc.code == 1000
