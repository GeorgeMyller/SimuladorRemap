"""``seq`` único por sessão (T163; tel RF-02, RF-03, RF-25; D-19; websocket-telemetry 2.1)."""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

from tel_helpers import FakeWebSocket, StubService, raw_event, raw_frame

from simremap.telemetry.broadcaster import TelemetryStream
from simremap.telemetry.contracts import TelemetryFrame, WsEnvelope
from simremap.telemetry.ws import TelemetryConnection


async def _connect(stream: TelemetryStream) -> tuple[TelemetryConnection, FakeWebSocket, Any]:
    ws = FakeWebSocket()
    conn = TelemetryConnection(ws, StubService(), "s", stream)  # type: ignore[arg-type]
    task = asyncio.create_task(conn.run(None))
    for _ in range(5):
        await asyncio.sleep(0)
    return conn, ws, task


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def test_error_between_two_frames_gets_n_plus_1() -> None:
    stream = TelemetryStream("s")
    _conn, ws, task = await _connect(stream)
    stream.publish(raw_frame(1, 0.02, rpm=3000.0))
    await _settle()
    ws.push({"v": 1, "type": "control.subscribe", "payload": {"channels": ["rpm", "nope"]}})
    await _settle()
    stream.publish(raw_frame(2, 0.04, rpm=3010.0))
    await _settle()
    seqs = [(m["type"], m["seq"]) for m in ws.sent]
    assert seqs[0][0] == "run.state"  # snapshot
    frame_n = next(s for t, s in seqs if t == "telemetry.frame")
    assert seqs[1:] == [
        ("telemetry.frame", frame_n),
        ("error", frame_n + 1),
        ("telemetry.frame", frame_n + 2),
    ]
    error = ws.sent[2]["payload"]
    assert error["code"] == "WS_UNKNOWN_CHANNEL" and error["detail"] == "nope"
    assert error["fatal"] is False and error["title"] == "Canal desconhecido"
    assert ws.sent[3]["payload"]["channels"] == {"rpm": 3010.0}  # canais válidos ativos
    task.cancel()


async def test_seq_starts_at_zero_and_is_shared_by_all_types() -> None:
    stream = TelemetryStream("s")
    out = [
        stream.publish(raw_frame(0, 0.0)),
        stream.publish(raw_event("event.knock", 0.01, run_id="r", cylinder=1)),
        stream.publish(raw_event("run.state", 0.02, run_id="r", state="arming")),
        stream.publish(raw_event("error", 0.02, code="SIM_INTERNAL_ERROR", title="x")),
    ]
    assert [o["seq"] for o in out if o is not None] == [0, 1, 2, 3]
    assert stream.allocate_seq() == 4
    assert stream.publish({"type": "ack", "payload": {}}) is None  # tipo interno do dyno
    assert stream.publish(raw_frame(1, 0.04))["seq"] == 5  # type: ignore[index]


async def test_10000_envelopes_with_50_errors_have_no_repeated_seq() -> None:
    stream = TelemetryStream("s")
    conn, ws, task = await _connect(stream)
    for i in range(10_000):
        if i % 200 == 199:
            conn.queue.offer(conn.error("WS_MESSAGE_INVALID", "injetado"))
        elif i % 7 == 3:
            stream.publish(
                raw_event(
                    "event.limiter",
                    i / 1000,
                    run_id="r",
                    kind="rev_limiter",
                    phase="hard",
                    active=bool(i % 2),
                    rpm=7000.0,
                )
            )
        else:
            stream.publish(raw_frame(i, i / 1000, rpm=float(i)))
        await asyncio.sleep(0)
    await _settle()
    seqs = [m["seq"] for m in ws.sent]
    assert len(seqs) == len(set(seqs))  # 0 repetições
    assert seqs[1:] == sorted(seqs[1:])  # ordem do seq na conexão
    assert sum(1 for m in ws.sent if m["type"] == "error") == 50
    assert len(ws.sent) >= 10_000
    for message in ws.sent:
        envelope = WsEnvelope.model_validate(message)
        assert envelope.v == 1
        if envelope.type == "telemetry.frame":
            TelemetryFrame.model_validate(envelope.payload)
    assert conn.queue.dropped_frames == 0
    task.cancel()


async def test_dropped_frames_appear_as_seq_gaps_but_not_frame_index_gaps() -> None:
    stream = TelemetryStream("s")
    conn, ws, task = await _connect(stream)
    stream.publish(raw_frame(0, 0.0, rpm=0.0))
    await _settle()
    ws.paused.clear()  # cliente parado
    await _settle()
    # 13 frames entram na fila de 8 sem o envio correr: 5 descartados.
    for i in range(1, 14):
        stream.publish(raw_frame(i, i / 50, rpm=float(i)))
    ws.paused.set()
    await _settle()
    frames = [m for m in ws.sent if m["type"] == "telemetry.frame"]
    indices = [f["payload"]["frame_index"] for f in frames]
    missing_seq = sum(b["seq"] - a["seq"] - 1 for a, b in itertools.pairwise(frames))
    lost = sum(b - a - 1 for a, b in itertools.pairwise(indices))
    assert conn.queue.dropped_frames == 5
    assert lost == 5  # perda medida por frame_index
    assert missing_seq == 5  # e vista como saltos de seq
    assert frames[-1]["payload"]["stats"]["dropped_frames"] == conn.queue.dropped_frames
    task.cancel()
