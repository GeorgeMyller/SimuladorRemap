"""Bloqueio mecânico e restauração (T105; physics RF-19, EC-13)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


def test_lock_stops_combustion_and_rpm(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-19: após lock, nenhum evento de combustão e rpm == 0 em ≤ 0,5 s."""
    engine = make_engine(hatch, noise_enabled=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=6000.0)
    engine.crank(6000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(1000):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None and state.rpm > 5000.0
    engine.lock("rod_failure")
    assert engine.last_reason == "rod_failure"
    stop_tick = None
    for k in range(600):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
        assert state.locked
        assert state.events == []  # comandos aceites, injeção e ignição ignoradas
        if state.rpm == 0.0 and stop_tick is None:
            stop_tick = k + 1
    assert stop_tick is not None and stop_tick * dt <= 0.5
    assert state.torque_nm <= 0.0 or state.rpm == 0.0
    assert engine.read_sensors().oil_pressure_kpa == 0.0
    engine.crank(3000.0)  # bloqueado: o motor de arranque não roda o eixo
    assert engine.rpm == 0.0


def test_reset_mechanical_restores_ambient_state(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    engine = make_engine(hatch, noise_enabled=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=4000.0)
    engine.crank(4000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(1500):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    engine.lock("piston_failure")
    tick = engine.vars.tick
    engine.reset_mechanical()
    v = engine.vars
    assert not v.locked and v.rpm == 0.0 and v.tick == tick
    assert v.ect_c == pytest.approx(25.0) and v.piston_c == [pytest.approx(25.0)] * 4
    assert v.p_man_kpa == pytest.approx(v.p_amb_kpa)
    assert v.turbo_omega == 0.0 and v.film_kg == [0.0] * 4
    engine.crank(2000.0)
    state = engine.step(
        driver.commands(engine.read_sensors(), dt), rig.load(None, engine.rpm, dt), dt
    )
    assert not state.locked and state.rpm > 0.0
