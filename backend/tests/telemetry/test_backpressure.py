"""Backpressure por conexão (T164, T338; tel RF-08, RF-09, RF-23; EC-01; D-05; ws 6)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import orjson
from tel_helpers import (
    FakeWebSocket,
    StubService,
    make_sampler_task,
    raw_event,
    raw_frame,
    start_run,
)

from simremap.telemetry.broadcaster import (
    EVENT_QUEUE_SIZE,
    FRAME_QUEUE_SIZE,
    ConnectionQueue,
    TelemetryStream,
)
from simremap.telemetry.ws import TelemetryConnection


def _env(type_: str, seq: int, t: float = 0.0, **payload: Any) -> dict[str, Any]:
    return {"v": 1, "type": type_, "seq": seq, "t_sim_s": t, "payload": payload}


def test_frame_queue_keeps_8_newest_and_counts_drops() -> None:
    queue = ConnectionQueue()
    for i in range(20):
        queue.offer(_env("telemetry.frame", i))
    assert len(queue.frames) == FRAME_QUEUE_SIZE
    assert queue.dropped_frames == 12
    assert [queue.pop()["seq"] for _ in range(8)] == list(range(12, 20))  # type: ignore[index]
    assert queue.pop() is None


def test_rf09_knock_dropped_but_never_run_state_or_failure() -> None:
    queue = ConnectionQueue()
    seq = 0
    critical = 0
    for i in range(300):
        queue.offer(_env("event.knock", seq, cylinder=1 + i % 4))
        seq += 1
        if i % 30 == 0:
            queue.offer(_env("run.state", seq, state="running"))
            queue.offer(_env("event.failure", seq + 1, mode="rod_failure"))
            queue.offer(_env("event.limiter", seq + 2, kind="rev_limiter"))
            queue.offer(_env("error", seq + 3, code="SIM_INTERNAL_ERROR"))
            seq += 4
            critical += 4
    assert queue.dropped_events >= 44
    kinds = [e["type"] for e in queue.events]
    assert len(kinds) <= EVENT_QUEUE_SIZE
    assert sum(k != "event.knock" for k in kinds) == critical  # 100 % dos críticos
    seqs = [e["seq"] for e in queue.events]
    assert seqs == sorted(seqs)


def test_critical_events_are_kept_even_beyond_capacity() -> None:
    queue = ConnectionQueue()
    for i in range(EVENT_QUEUE_SIZE + 10):
        queue.offer(_env("run.state", i))
    assert len(queue.events) == EVENT_QUEUE_SIZE + 10 and queue.dropped_events == 0


def test_output_follows_seq_order_across_queues() -> None:
    queue = ConnectionQueue()
    queue.offer(_env("telemetry.frame", 5))
    queue.offer(_env("run.state", 6))
    queue.offer(_env("telemetry.frame", 7))
    queue.offer(_env("event.knock", 8))
    assert [queue.pop()["seq"] for _ in range(4)] == [5, 6, 7, 8]  # type: ignore[index]


async def test_dropped_events_reported_in_next_frame() -> None:
    stream = TelemetryStream("s")
    ws = FakeWebSocket()
    conn = TelemetryConnection(ws, StubService(), "s", stream)  # type: ignore[arg-type]
    task = asyncio.create_task(conn.run(None))
    await asyncio.sleep(0.01)
    ws.paused.clear()
    for i in range(300):
        stream.publish(raw_event("event.knock", i / 1000, run_id="r", cylinder=1 + i % 4))
    stream.publish(raw_event("run.state", 0.31, run_id="r", state="completed"))
    stream.publish(raw_frame(16, 0.32, rpm=1.0))
    ws.paused.set()
    await asyncio.sleep(0.05)
    frame = next(m for m in ws.sent if m["type"] == "telemetry.frame")
    assert frame["payload"]["stats"]["dropped_events"] >= 44
    assert any(
        m["type"] == "run.state" and m["payload"].get("state") == "completed" for m in ws.sent
    )
    task.cancel()


async def test_stalled_client_for_10s_does_not_block_the_loop() -> None:
    """Cliente parado 10 s simulados com o laço real (hatch, 1000 Hz, TelemetrySampler)."""
    sim = make_sampler_task()
    stream = TelemetryStream(sim.session.payload.session_id)
    ws = FakeWebSocket()
    conn = TelemetryConnection(ws, StubService(), "s", stream)  # type: ignore[arg-type]
    task = asyncio.create_task(conn.run(None))
    await asyncio.sleep(0.01)
    ws.paused.clear()  # o cliente deixa de ler
    start_run(sim, {"run_type": "sweep_pull", "end_rpm": 6000, "ramp_rate_rpm_s": 300})
    spent = 0.0
    run_states = 0
    latest_t = 0.0
    for _ in range(10_000):
        sim.step()
        for raw in sim.drain_outputs():
            t0 = time.perf_counter()
            out = stream.publish(raw)
            spent += time.perf_counter() - t0
            if out is not None:
                latest_t = max(latest_t, out["t_sim_s"])
                run_states += out["type"] == "run.state"
    # O produtor nunca espera pelo socket: custo no event loop ≤ 1 % dos 10 s simulados.
    assert spent < 0.1
    queue = conn.queue
    assert len(queue.frames) <= FRAME_QUEUE_SIZE and queue.dropped_frames > 400
    memory = sum(len(orjson.dumps(e)) for e in (*queue.frames, *queue.events))
    assert memory <= 2 * 1024 * 1024
    assert run_states >= 2
    assert sum(e["type"] == "run.state" for e in queue.events) == run_states  # 100 %
    ws.paused.set()
    await asyncio.sleep(0.05)
    frames = [m for m in ws.sent if m["type"] == "telemetry.frame"]
    assert len(frames) >= FRAME_QUEUE_SIZE
    # Depois do frame que já estava no envio, tudo está a ≤ 200 ms do tempo atual.
    assert all(latest_t - f["t_sim_s"] <= 0.2 for f in frames[-FRAME_QUEUE_SIZE:])
    dropped = [f["payload"]["stats"]["dropped_frames"] for f in frames]
    assert dropped == sorted(dropped) and dropped[-1] == queue.dropped_frames
    task.cancel()
