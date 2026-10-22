"""Benchmark do passo físico (T107; physics RNF-01, G-02; D-06).

Cenário pior caso: ``muscle-v8-sc`` a 7500 rpm WOT a 1000 Hz (500 eventos/s), com
``read_sensors`` + ``step`` por tick (o orçamento de 0,5 ms do barramento cobre os dois).
Critério: média ≤ 0,5 ms e p99 ≤ 2,0 ms por tick. Corre só com ``-m bench`` (D-26).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import EngineState
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig

MEAN_BUDGET_S = 0.5e-3
P99_BUDGET_S = 2.0e-3


def _prepare(
    make_engine: Callable[..., PhysicsEngine], vehicle: VehicleSpec, cache: int
) -> tuple[PhysicsEngine, Any, RpmHoldRig, EngineState]:
    engine = make_engine(vehicle, sim_hz=1000, cycle_cache_size=cache, seed=1)
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=7500.0)
    engine.crank(7500.0)
    dt = engine.resolved.dt
    state: EngineState | None = None
    for _ in range(3000):  # regime: boost, temperaturas e cache
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None
    commands = driver.commands(engine.read_sensors(), dt)
    return engine, commands, rig, state


@pytest.mark.parametrize("cache", [4096, 0], ids=["cache", "sem-cache"])
def test_bench_step_v8_7500_wot(
    benchmark: Any, make_engine: Callable[..., PhysicsEngine], muscle: VehicleSpec, cache: int
) -> None:
    engine, commands, rig, first = _prepare(make_engine, muscle, cache)
    dt = engine.resolved.dt
    last = [first]

    def tick() -> None:
        # O banco PI (custo do dyno, ≤ 50 µs) entra na medição para segurar 7500 rpm.
        load = rig.load(last[0], engine.rpm, dt)
        engine.read_sensors()
        last[0] = engine.step(commands, load, dt)

    benchmark.pedantic(tick, rounds=5000, iterations=1, warmup_rounds=200)
    # p99 medido à parte (o pytest-benchmark não expõe percentis).
    samples = []
    for _ in range(5000):
        t0 = time.perf_counter()
        tick()
        samples.append(time.perf_counter() - t0)
    samples.sort()
    p99 = samples[int(0.99 * len(samples))]
    mean = benchmark.stats.stats.mean
    benchmark.extra_info.update(
        {"p99_ms": p99 * 1e3, "mean_ms": mean * 1e3, "events_per_tick": 0.5, "cache_size": cache}
    )
    assert engine.rpm == pytest.approx(7500.0, rel=0.02)
    assert mean <= MEAN_BUDGET_S
    assert p99 <= P99_BUDGET_S
