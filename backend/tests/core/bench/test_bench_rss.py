"""Benchmark de memória: RSS em carga dentro do limite do container (T149; RF-18; OQ-02).

1 sessão no modo ``process`` a 1000 Hz com frames a 50 FPS consumidos e pedidos de
health contínuos durante ``SIMREMAP_BENCH_RSS_SECONDS`` (padrão 600 s = 10 min). O RSS
somado do processo da API e dos filhos (``ps -o rss=``) fica ≤ 1,5 GB (RF-18), dentro do
``mem_limit`` de 3 GB do ``compose.prod.yaml``. Para medir o container real, use
``scripts/smoke_container.sh`` (``docker stats``) com o mesmo ``make bench``.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest
from asgi_lifespan import LifespanManager

from simremap.api.main import create_app

pytestmark = pytest.mark.bench

SECONDS = float(os.environ.get("SIMREMAP_BENCH_RSS_SECONDS", "600"))
LIMIT_MB = float(os.environ.get("SIMREMAP_BENCH_RSS_LIMIT_MB", "1536"))
CONTAINER_LIMIT_MB = 3072.0
REPORT = Path(os.environ.get("SIMREMAP_BENCH_RSS_REPORT", ".bench/rss.json"))


def _rss_mb(pids: list[int]) -> float:
    ps = shutil.which("ps")
    if ps is None:  # pragma: no cover - ps existe em Linux e macOS
        pytest.skip("ps indisponível")
    out = subprocess.run(  # noqa: S603 - binário do sistema com PIDs numéricos
        [ps, "-o", "rss=", "-p", ",".join(map(str, pids))],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return sum(int(v) for v in out.split() if v.isdigit()) / 1024.0


def _write_report(text: str) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, "utf-8")


async def test_bench_rss_under_load(settings_factory: Any) -> None:
    app = create_app(settings_factory(worker_mode="process", log_level="WARNING"))
    payload = orjson.dumps({"sim_hz": 1000, "fps": 50, "busy_us": 300, "knock_every": 100})
    samples: list[float] = []
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        host = app.state.worker_host
        handle = await host.start_session(
            "rss", "simremap.core.worker.synthetic:SyntheticTask", payload, sim_hz=1000
        )
        child = handle.backend.pid
        stop = asyncio.Event()

        async def consume() -> None:
            async for _ in handle.outputs():
                if stop.is_set():
                    return

        consumer = asyncio.create_task(consume())
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bench") as ac:
            t_start = time.perf_counter()
            next_sample = t_start
            while time.perf_counter() - t_start < SECONDS:
                await ac.get("/api/v1/health")
                if time.perf_counter() >= next_sample:
                    samples.append(_rss_mb([os.getpid(), child]))
                    next_sample += 5.0
                await asyncio.sleep(0.1)
        stats = handle.stats
        stop.set()
        await host.stop_session("rss")
        await asyncio.wait_for(consumer, 10)
    report = {
        "seconds": SECONDS,
        "rss_max_mb": round(max(samples), 1),
        "rss_first_mb": round(samples[0], 1),
        "rss_last_mb": round(samples[-1], 1),
        "samples": len(samples),
        "achieved_hz": round(stats.achieved_hz, 1),
        "limit_mb": LIMIT_MB,
    }
    await asyncio.to_thread(_write_report, json.dumps(report, indent=2))
    print(json.dumps(report))
    assert max(samples) <= LIMIT_MB <= CONTAINER_LIMIT_MB
