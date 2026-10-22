"""Benchmark da telemetria (T171; tel RNF-01 a RNF-03; G-03). ``pytest -m bench``.

- Amostrador ``TelemetrySampler.on_tick`` P95 ≤ 60 µs por tick a 1000 Hz com 8 cilindros
  (muscle V8 da fixture da física, puxada real com log aberto, frames e blocos de log).
- Latência tick → envio P95 ≤ 40 ms e P99 ≤ 80 ms: do ``publish`` do frame no event loop até
  ao ``send_text`` de 2 conexões.
- Banda ≤ 150 kB/s por conexão com a subscrição completa da cockpit e espectro a 50 FPS,
  medida no fio com o permessage-deflate do uvicorn (o JSON cru com ``bins_hz`` de 256 valores
  em todo frame fica acima disso; o valor é impresso).
"""

from __future__ import annotations

import asyncio
import time
import zlib
from typing import Any

import numpy as np
import orjson
from dyno_helpers import _physics_fixtures, catalog_fuels
from tel_helpers import FakeWebSocket, StubService, make_sampler_task, start_run

from simremap.telemetry.broadcaster import TelemetryStream
from simremap.telemetry.ws import TelemetryConnection

SWEEP = {"run_type": "sweep_pull", "end_rpm": 5000, "ramp_rate_rpm_s": 1000}
COCKPIT = [
    "rpm", "power_kw", "torque_nm", "lambda", "egt_c", "map_kpa", "baro_kpa", "iat_c", "ect_c",
    "knock_retard_deg", "roller_speed_kmh", "overrun_afterfire", "throttle_pct", "turbo_rpm",
]  # fmt: skip


def _v8_task() -> Any:
    vehicle = _physics_fixtures().build_muscle()
    return make_sampler_task(vehicle=vehicle, fuel=catalog_fuels()[vehicle.stock_fuel_id])


def test_sampler_p95_under_60_us_with_8_cylinders() -> None:
    task = _v8_task()
    sampler = task.session.sampler
    assert sampler.n_cyl == 8
    sampler.bind_spectrum(task.session.damage.spectrum_frame)
    original = sampler.on_tick
    samples: list[float] = []

    def timed(rec: Any) -> None:
        t0 = time.perf_counter()
        original(rec)
        samples.append(time.perf_counter() - t0)

    sampler.on_tick = timed
    start_run(task, dict(SWEEP))
    for _ in range(5000):
        task.step()
        task.drain_outputs()
    p95 = float(np.percentile(samples, 95))
    print(
        f"sampler V8 1000 Hz: p50 = {np.percentile(samples, 50) * 1e6:.1f} µs, "
        f"p95 = {p95 * 1e6:.1f} µs"
    )
    assert p95 <= 60e-6


async def test_latency_and_bandwidth_full_cockpit_subscription() -> None:
    task = make_sampler_task()
    task.session.sampler.bind_spectrum(task.session.damage.spectrum_frame)  # type: ignore[attr-defined]
    stream = TelemetryStream("s")
    sockets = [FakeWebSocket(), FakeWebSocket()]
    conns = [TelemetryConnection(ws, StubService(), "s", stream) for ws in sockets]  # type: ignore[arg-type]
    tasks = [asyncio.create_task(c.run(None)) for c in conns]
    await asyncio.sleep(0.01)
    channels = COCKPIT + [f"knock_intensity_cyl{k}" for k in range(1, 5)]
    channels += [f"knock_sensor_v_cyl{k}" for k in range(1, 5)]
    for ws in sockets:
        ws.push(
            {
                "v": 1,
                "type": "control.subscribe",
                "payload": {
                    "channels": channels,
                    "spectrum": True,
                    "pressure_trace": {"cylinder": 1},
                },
            }
        )
    await asyncio.sleep(0.01)
    loop = asyncio.get_running_loop()
    published: dict[int, float] = {}
    task.handle_command({"type": "operator.throttle", "throttle_pct": 40.0})
    start_run(task, dict(SWEEP))
    for _ in range(5000):
        task.step()
        for raw in task.drain_outputs():
            out = stream.publish(raw)
            if out is not None and out["type"] == "telemetry.frame":
                published[out["seq"]] = loop.time()
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    for ws, conn in zip(sockets, conns, strict=True):
        frames = [m for m in ws.sent if m["type"] == "telemetry.frame"]
        assert len(frames) >= 240 and conn.queue.dropped_frames == 0
        encoded = [orjson.dumps(f) for f in frames]
        # No fio: permessage-deflate (padrão do uvicorn/websockets; janela de 12 bits).
        deflate = zlib.compressobj(6, zlib.DEFLATED, -12, 5)
        wire = [len(deflate.compress(m) + deflate.flush(zlib.Z_SYNC_FLUSH)) - 4 for m in encoded]
        json_bw = float(np.mean([len(m) for m in encoded])) * 50
        wire_bw = float(np.mean(wire)) * 50
        print(
            f"banda por conexão (50 FPS, espectro): JSON {json_bw / 1024:.1f} kB/s, "
            f"no fio {wire_bw / 1024:.1f} kB/s"
        )
        assert wire_bw <= 150 * 1024
        assert all(f["payload"]["knock_spectrum"] is not None for f in frames[1:])
    # Latência: medida com o relógio do event loop entre publish e send (FakeWebSocket).
    latencies: list[float] = []

    class _Clocked(FakeWebSocket):
        async def send_text(self, text: str) -> None:
            message = orjson.loads(text)
            if message["type"] == "telemetry.frame" and message["seq"] in published:
                latencies.append(loop.time() - published[message["seq"]])
            await super().send_text(text)

    clocked = [_Clocked(), _Clocked()]
    more = [TelemetryConnection(ws, StubService(), "s", stream) for ws in clocked]  # type: ignore[arg-type]
    tasks += [asyncio.create_task(c.run(None)) for c in more]
    await asyncio.sleep(0.01)
    published.clear()
    for _ in range(3000):
        task.step()
        for raw in task.drain_outputs():
            out = stream.publish(raw)
            if out is not None and out["type"] == "telemetry.frame":
                published[out["seq"]] = loop.time()
        await asyncio.sleep(0)
    await asyncio.sleep(0.05)
    assert latencies
    p95, p99 = np.percentile(latencies, [95, 99])
    print(f"latência publish→send: p95 = {p95 * 1e3:.2f} ms, p99 = {p99 * 1e3:.2f} ms")
    assert p95 <= 0.040 and p99 <= 0.080
    for t in tasks:
        t.cancel()
