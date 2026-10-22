"""Benchmark comparativo ``process`` × ``thread`` do worker (T083; D-04; platform OQ-01).

Critério de D-04 (hardware de referência, 4 núcleos): com 1 sessão a 1000 Hz e frames a
50 FPS consumidos pelo event loop, ``GET /api/v1/health`` P95 < 50 ms e lag do event
loop (timer de 10 ms) P99 < 20 ms, com o worker a ≥ 99 % de ``sim_hz``.

Carga: ``PhysicsOnlyTask`` (T408) com a física real (padrão ``muscle-v8-sc``, o motor mais
pesado: 8 cilindros, a 6000 rpm em plena carga, ruído ligado); ``SIMREMAP_BENCH_TASK=synthetic``
volta à ``SyntheticTask`` com ``busy_us`` de laço Python por tick.

Execução: ``make bench`` (ou ``pytest -m bench tests/core/bench``). Variáveis:
``SIMREMAP_BENCH_SECONDS`` (padrão 10), ``SIMREMAP_BENCH_VEHICLE`` (padrão ``muscle-v8-sc``),
``SIMREMAP_BENCH_RPM`` (padrão 6000), ``SIMREMAP_BENCH_BUSY_US`` (padrão 300) e
``SIMREMAP_BENCH_REPORT`` (JSON com os resultados; padrão ``.bench/worker_modes.json``).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app

pytestmark = pytest.mark.bench

SECONDS = float(os.environ.get("SIMREMAP_BENCH_SECONDS", "10"))
BUSY_US = int(os.environ.get("SIMREMAP_BENCH_BUSY_US", "300"))
TASK_KIND = os.environ.get("SIMREMAP_BENCH_TASK", "physics")
VEHICLE = os.environ.get("SIMREMAP_BENCH_VEHICLE", "muscle-v8-sc")
RPM = float(os.environ.get("SIMREMAP_BENCH_RPM", "6000"))
REPORT = Path(os.environ.get("SIMREMAP_BENCH_REPORT", ".bench/worker_modes.json"))
SIM_HZ = 1000


def _task() -> tuple[str, bytes]:
    if TASK_KIND == "physics" and importlib.util.find_spec("simremap.core.worker.physics_task"):
        payload = orjson.dumps({"vehicle_id": VEHICLE, "rpm": RPM, "sim_hz": SIM_HZ, "fps": 50})
        return "simremap.core.worker.physics_task:PhysicsOnlyTask", payload
    payload = orjson.dumps({"sim_hz": SIM_HZ, "fps": 50, "busy_us": BUSY_US})
    return "simremap.core.worker.synthetic:SyntheticTask", payload


def _write_report(text: str) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, "utf-8")


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


async def _measure(mode: str, settings_factory: Any) -> dict[str, Any]:
    app = create_app(settings_factory(worker_mode=mode, log_level="WARNING"))
    task, payload = _task()
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        host = app.state.worker_host
        handle = await host.start_session("bench", task, payload, sim_hz=SIM_HZ)
        frames = 0
        stop = asyncio.Event()

        async def consume() -> None:
            nonlocal frames
            async for raw in handle.outputs():
                if b"telemetry.frame" in raw:
                    frames += 1
                if stop.is_set():
                    return

        lags: list[float] = []

        async def lag_probe() -> None:
            while not stop.is_set():
                t0 = time.perf_counter()
                await asyncio.sleep(0.010)
                lags.append((time.perf_counter() - t0 - 0.010) * 1000)

        consumer = asyncio.create_task(consume())
        probe = asyncio.create_task(lag_probe())
        latencies: list[float] = []
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench") as ac:
            await asyncio.sleep(1.0)  # aquecimento
            ticks0 = handle.stats.ticks
            t_start = time.perf_counter()
            while time.perf_counter() - t_start < SECONDS:
                t0 = time.perf_counter()
                resp = await ac.get("/api/v1/health")
                latencies.append((time.perf_counter() - t0) * 1000)
                assert resp.status_code == 200
                await asyncio.sleep(0.05)
            elapsed = time.perf_counter() - t_start
            ticks = handle.stats.ticks - ticks0
        stop.set()
        stats = handle.stats
        await host.stop_session("bench")
        await asyncio.wait_for(consumer, 10)
        await probe
    return {
        "mode": mode,
        "task": task,
        "busy_us": BUSY_US if "synthetic" in task else None,
        "vehicle_id": VEHICLE if "physics" in task else None,
        "rpm": RPM if "physics" in task else None,
        "seconds": round(elapsed, 2),
        "achieved_hz": round(ticks / elapsed, 1),
        "rtf": round(ticks / elapsed / SIM_HZ, 4),
        "frames_per_s": round(frames / (elapsed + 1.0), 1),
        "health_p95_ms": round(_pct(latencies, 0.95), 3),
        "loop_lag_p99_ms": round(_pct(lags, 0.99), 3),
        "overrun_ticks": stats.overrun_ticks,
        "dropped_outputs": stats.dropped_outputs,
        "cpu_count": os.cpu_count(),
    }


async def test_bench_worker_modes(settings_factory: Any) -> None:
    results = [await _measure(mode, settings_factory) for mode in ("process", "thread")]
    passed = {
        r["mode"]: r["health_p95_ms"] < 50 and r["loop_lag_p99_ms"] < 20 and r["rtf"] >= 0.99
        for r in results
    }
    decision = "process" if passed["process"] else ("thread" if passed["thread"] else "none")
    report = {"criteria": "D-04", "results": results, "passed": passed, "decision": decision}
    await asyncio.to_thread(_write_report, json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, ensure_ascii=False))
    assert passed["process"], f"modo process fora do critério D-04: {results[0]}"
