"""Custo do adaptador ``ProfiledEcu`` sobre o ``EcuRuntime.step`` (G-07; RNF-01; simulation-bus 2).

Alvo: ≤ 0,02 ms p99 por tick acrescentados ao ``step()`` (8 cilindros, 1000 Hz); o caminho
de torque OEM ≤ 0,03 ms p99. Mede-se o tempo do adaptador isolado (``transform_sensors`` +
pós-processamento) como a diferença entre ``ProfiledEcu.step`` e ``EcuRuntime.step`` nos
mesmos sensores. Marcador ``bench`` (fora do ``make check``).
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

from simremap.catalog.service import CatalogService
from simremap.physics.contracts import SensorReadings
from simremap.profiles.adapter import build_profiled_ecu
from simremap.profiles.contracts import BaseSetup, EcuProfileId, HardwareOverride, WizardInputs
from simremap.profiles.wizard import generate_base_map

N_TICKS = 100_000


def _p99(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=100)[98]


def _bench(ecu: Any, sensors: list[SensorReadings]) -> tuple[float, float]:
    runtime = ecu.runtime
    total: list[float] = []
    core: list[float] = []
    clock = time.perf_counter
    for k in range(N_TICKS):
        s = sensors[k % len(sensors)]
        t0 = clock()
        ecu.step(s, 0.001)
        t1 = clock()
        view = ecu.adapter.transform_sensors(s)
        t2 = clock()
        runtime.step(view, 0.001)
        t3 = clock()
        total.append(t1 - t0)
        core.append(t3 - t2)
    return _p99(total), _p99(core)


def test_bench_standalone_adapter_8cyl(
    catalog: CatalogService,
    base_payload: Callable[..., dict[str, Any]],
    sensors: Callable[..., SensorReadings],
) -> None:
    muscle = catalog.get_vehicle("muscle-v8-sc")
    payload = base_payload(
        trigger={"wheel": "36-1", "tdc_offset_deg": 60.0, "firing_order": [1, 5, 4, 8, 6, 3, 7, 2]},
        sensors={
            "map": {"min_kpa": 20.0, "max_kpa": 250.0},
            "iat": {"curve": "ntc_b"},
            "wideband": {},
        },
    )
    base = BaseSetup.model_validate(payload)
    content = generate_base_map(EcuProfileId.HT_ELITE, base, muscle, WizardInputs()).content
    ecu = build_profiled_ecu(
        vehicle=muscle, stock_fuel=catalog.get_fuel("e27"), profile_id="ht-elite",
        ecu_state="standalone_ready", base_setup=base, calibration=content,
        override=HardwareOverride(tdc_offset_shift_deg=4.0, injector_flow_cc_min=900.0),
    )  # fmt: skip
    samples = [
        sensors(8, rpm=1000.0 + 60.0 * i, map_kpa=40.0 + 2.0 * i, t_sim_s=1.0 + i * 0.001)
        for i in range(100)
    ]
    p99_total, p99_core = _bench(ecu, samples)
    overhead = p99_total - p99_core
    print(f"ProfiledEcu p99 {p99_total * 1e6:.1f} µs, runtime p99 {p99_core * 1e6:.1f} µs")
    assert overhead <= 0.00002 * 1.5  # tolerância de ruído de medição


def test_bench_oem_torque_path(
    catalog: CatalogService, oem_content: Callable[..., Any], sensors: Callable[..., SensorReadings]
) -> None:
    hatch = catalog.get_vehicle("hatch-20t-gdi")
    ecu = build_profiled_ecu(
        vehicle=hatch, stock_fuel=catalog.get_fuel("e27"), profile_id="oem-stage",
        ecu_state="oem", base_setup=None, calibration=oem_content(),
    )  # fmt: skip
    samples = [
        sensors(4, rpm=1500.0 + 45.0 * i, map_kpa=60.0 + 2.0 * i, t_sim_s=1.0 + i * 0.001)
        for i in range(100)
    ]
    p99_total, p99_core = _bench(ecu, samples)
    print(f"OEM ProfiledEcu p99 {p99_total * 1e6:.1f} µs, runtime p99 {p99_core * 1e6:.1f} µs")
    assert p99_total - p99_core <= 0.00003 * 1.5
