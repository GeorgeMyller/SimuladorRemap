"""Benchmark de ``EcuRuntime.step`` (ecu-core RNF-01, G-01; T148).

100 000 ticks a 1000 Hz, 8 cilindros, todas as estratégias ativas: p99 ≤ 0,1 ms.
O máximo absoluto (≤ 0,5 ms na spec) depende do escalonador do SO; aqui exige-se o
percentil 99,9 ≤ 0,5 ms e o máximo é reportado. Marcador ``bench`` (fora de ``make check``):
``pytest -m bench tests/ecu/bench``.
"""

from __future__ import annotations

import gc
import time
from typing import Any

N_TICKS = 100_000
DT = 0.001


def test_bench_ecu_step_p99(full_content: Any, runtime_factory: Any, sensors: Any) -> None:
    rt = runtime_factory(full_content, n_cyl=8)
    readings = []
    for i in range(1000):
        knock = [0.5 if (i + k) % 37 == 0 else 0.0 for k in range(8)]
        readings.append(
            sensors(
                n_cyl=8,
                rpm=3000.0 + 4.0 * i,
                map_kpa=120.0 + (i % 100),
                tps_pct=float(i % 101),
                lambda_measured=0.80 + (i % 20) / 100,
                knock_intensity=knock,
                clutch_pressed=i % 500 < 100,
                shift_request=i % 250 < 5,
                antilag_switch=i % 300 < 50,
                egt_collector_c=850.0 + (i % 150),
            )
        )
    times = [0.0] * N_TICKS
    gc.collect()
    gc.disable()
    try:
        for i in range(N_TICKS):
            s = readings[i % 1000].model_copy(update={"t_sim_s": i * DT, "tick": i})
            t0 = time.perf_counter()
            rt.step(s, DT)
            times[i] = time.perf_counter() - t0
    finally:
        gc.enable()
    times.sort()
    p99 = times[int(N_TICKS * 0.99)]
    p999 = times[int(N_TICKS * 0.999)]
    print(
        f"\nEcuRuntime.step: p50 {times[N_TICKS // 2] * 1e6:.1f} µs, p99 {p99 * 1e6:.1f} µs, "
        f"p99.9 {p999 * 1e6:.1f} µs, máx {times[-1] * 1e6:.1f} µs"
    )
    assert p99 <= 0.0001
    assert p999 <= 0.0005
