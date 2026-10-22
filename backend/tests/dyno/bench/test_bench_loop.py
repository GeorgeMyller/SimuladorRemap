"""Benchmark do laço completo do dinamômetro (T128; dyno RNF-01, G-02; simulation-bus 2).

- Fator de tempo real ≥ 1,0 a 100 Hz nos 4 veículos (obrigatório) e a 1000 Hz no hatch
  (alvo, registado e verificado), com física + ECU + dano + telemetria numa
  ``sweep_pull`` 2000 → 4000 rpm.
- Custo próprio do dyno-bench (controladores, ``DynoLoad``, medição, máquina de estados)
  P95 ≤ 50 µs por tick: tempo do passo menos os estágios de física, ECU, dano e sampler.

Os 4 ``VehicleSpec`` vêm da fixture da física; coupe/classic/muscle usam a calibração do
hatch recompilada para o seu ``n_cyl`` (o custo por tick é o que se mede). Corre com
``pytest -m bench`` (marcador automático do diretório).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from dyno_helpers import _physics_fixtures, make_task, run_to_result

from simremap.dyno.runner import DynoSimTask

SWEEP = {"run_type": "sweep_pull", "end_rpm": 4000, "ramp_rate_rpm_s": 1000}
DYNO_P95_BUDGET_S = 50e-6


def _vehicle(name: str) -> Any:
    return getattr(_physics_fixtures(), f"build_{name}")()


class _Timed:
    def __init__(self, real: Any, bucket: list[float], method: str) -> None:
        self._real = real
        self._bucket = bucket
        self._method = method

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._real, name)
        if name not in (self._method, "read_sensors"):
            return attr

        def timed(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return attr(*args, **kwargs)
            finally:
                self._bucket.append(time.perf_counter() - t0)

        return timed


def _rtf(task: DynoSimTask) -> float:
    t_sim0 = task.t_sim_s
    t0 = time.perf_counter()
    run_to_result(task, dict(SWEEP))
    wall = time.perf_counter() - t0
    return (task.t_sim_s - t_sim0) / wall


@pytest.mark.parametrize("name", ["hatch", "coupe", "classic", "muscle"])
def test_realtime_factor_at_100_hz(name: str) -> None:
    vehicle = _vehicle(name)
    fuel_id = vehicle.stock_fuel_id
    from dyno_helpers import catalog_fuels

    task = make_task(vehicle=vehicle, fuel=catalog_fuels()[fuel_id], sim_hz=100)
    factor = _rtf(task)
    print(f"{name}: fator de tempo real a 100 Hz = {factor:.2f}")
    assert factor >= 1.0


def test_realtime_factor_target_1000_hz_hatch() -> None:
    factor = _rtf(make_task(sim_hz=1000))
    print(f"hatch: fator de tempo real a 1000 Hz = {factor:.2f}")
    assert factor >= 1.0


def test_dyno_orchestration_p95_under_50_us() -> None:
    task = make_task(sim_hz=1000)
    stages: list[float] = []
    parts = task.session
    parts.physics = _Timed(parts.physics, stages, "step")  # type: ignore[assignment]
    parts.ecu = _Timed(parts.ecu, stages, "step")
    parts.damage = _Timed(parts.damage, stages, "step")  # type: ignore[assignment]
    task._main_damage = parts.damage
    parts.sampler = _Timed(parts.sampler, stages, "on_tick")
    task.handle_command(
        {"type": "run.start", "run_id": "01JAB0000000000000000000DD", "request": dict(SWEEP)}
    )
    own: list[float] = []
    for _ in range(4000):
        stages.clear()
        t0 = time.perf_counter()
        task.step()
        total = time.perf_counter() - t0
        own.append(total - sum(stages))
        task.drain_outputs()
    own.sort()
    p95 = own[int(0.95 * len(own))]
    print(f"custo próprio do dyno P95 = {p95 * 1e6:.1f} µs")
    assert p95 <= DYNO_P95_BUDGET_S
