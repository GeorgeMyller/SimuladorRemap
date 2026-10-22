"""Falhas físicas injetadas (T104; physics RF-23)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import EngineState, PhysicsFault
from simremap.physics.engine import PhysicsEngine
from simremap.physics.faults import ActiveFaults
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


def _run(  # noqa: PLR0917
    make_engine: Callable[..., PhysicsEngine],
    vehicle: VehicleSpec,
    rpm: float,
    faults: list[PhysicsFault],
    seconds: float = 5.0,
    duty: float | None = None,
    **driver_kw: Any,
) -> tuple[PhysicsEngine, ReferenceDriver, EngineState]:
    engine = make_engine(vehicle, noise_enabled=False, sim_hz=500, faults=faults)
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule, **driver_kw)
    driver.duty_override = duty
    rig = RpmHoldRig(target_rpm=rpm)
    engine.crank(rpm)
    dt = engine.resolved.dt
    state = None
    for _ in range(round(seconds / dt)):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None
    return engine, driver, state


def test_active_faults_queries() -> None:
    faults = ActiveFaults(
        [
            PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=120.0),
            PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=60.0, start_t_sim_s=2.0),
            PhysicsFault(kind="injector_clogged", cylinder=2, injector_flow_factor=0.8),
            PhysicsFault(kind="boost_leak", leak_area_mm2=50.0),
            PhysicsFault(kind="sensor_bias", sensor_channel="iat_c", sensor_bias=-15.0),
            PhysicsFault(kind="wastegate_stuck", stuck_position_pct=25.0, start_t_sim_s=1.0),
        ],
        4,
    )
    assert faults.fuel_pump_max_lph(0.0) == 120.0
    assert faults.fuel_pump_max_lph(3.0) == 60.0
    assert faults.injector_factors(0.0) == [1.0, 0.8, 1.0, 1.0]
    assert faults.leak_cd_area_m2(0.0) == pytest.approx(0.7 * 50e-6)
    assert faults.sensor_bias(0.0) == {"iat_c": -15.0}
    assert faults.wastegate_stuck_fraction(0.5) is None
    assert faults.wastegate_stuck_fraction(1.0) == pytest.approx(0.25)
    empty = ActiveFaults([], 4)
    assert not empty and empty.fuel_pump_max_lph(0.0) is None


def test_fuel_pump_weak_leans_full_load(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-23: teto 60 L/h reduz a pressão de rail e empobrece o λ ≥ 5 % a plena carga."""
    _, _, healthy = _run(make_engine, hatch, 5000.0, [])
    engine, _, weak = _run(
        make_engine, hatch, 5000.0, [PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=60.0)]
    )
    assert healthy.lambda_collector is not None and weak.lambda_collector is not None
    assert weak.lambda_collector >= 1.05 * healthy.lambda_collector
    assert engine.read_sensors().fuel_pressure_kpa < 0.5 * 20_000
    # A vazão entregue fica no teto (60 L/h · ρ).
    assert weak.fuel_flow_g_s == pytest.approx(60 / 3600 * 745, rel=0.05)


def test_injector_clogged_leans_one_cylinder(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    _, _, state = _run(
        make_engine,
        hatch,
        3000.0,
        [PhysicsFault(kind="injector_clogged", cylinder=3, injector_flow_factor=0.8)],
        seconds=2.0,
        throttle_pct=40.0,
        lambda_target=1.0,
    )
    lam = state.lambda_cyl
    assert lam[2] is not None and lam[0] is not None
    assert lam[2] == pytest.approx(lam[0] / 0.8, rel=0.02)


def test_boost_leak_lowers_boost(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """Fuga de boost: com a wastegate fechada (turbo no limite) o MAP cai; regulada, o turbo
    gira mais depressa para compensar a fuga."""
    leak = [PhysicsFault(kind="boost_leak", leak_area_mm2=300.0)]
    _, _, tight = _run(make_engine, hatch, 2500.0, [], duty=100.0)
    _, _, leaky = _run(make_engine, hatch, 2500.0, leak, duty=100.0)
    assert leaky.map_kpa < tight.map_kpa - 5.0
    _, _, reg = _run(make_engine, hatch, 4000.0, [], duty=60.0)
    _, _, reg_leak = _run(make_engine, hatch, 4000.0, leak, duty=60.0)
    assert reg.turbo_rpm is not None and reg_leak.turbo_rpm is not None
    assert reg_leak.turbo_rpm > reg.turbo_rpm


def test_sensor_bias_shifts_reading_not_physics(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    fault = PhysicsFault(
        kind="sensor_bias", sensor_channel="iat_c", sensor_bias=20.0, start_t_sim_s=0.5
    )
    engine, _, _ = _run(make_engine, hatch, 2500.0, [fault], seconds=0.4, throttle_pct=20.0)
    before = engine.read_sensors()
    assert before.iat_c == pytest.approx(engine.vars.t_man_k - 273.15)
    engine2, _, _ = _run(make_engine, hatch, 2500.0, [fault], seconds=1.0, throttle_pct=20.0)
    after = engine2.read_sensors()
    assert after.iat_c == pytest.approx(engine2.vars.t_man_k - 273.15 + 20.0)


def test_wastegate_stuck_closed_overboosts(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-23: wastegate presa fechada ⇒ MAP ≥ 1,15 × alvo da ECU a plena carga."""
    _, driver, state = _run(
        make_engine, hatch, 4000.0, [PhysicsFault(kind="wastegate_stuck", stuck_position_pct=0.0)]
    )
    target = driver.point().map_target_kpa
    assert state.map_kpa >= 1.15 * target
    assert state.wastegate_position_pct == 0.0


@pytest.mark.parametrize("duty", [0.0, 50.0, 100.0])
def test_wastegate_stuck_open_caps_boost(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec, duty: float
) -> None:
    """RF-23: wastegate presa a 100 % ⇒ boost ≤ mola + 10 kPa para qualquer duty."""
    _, _, state = _run(
        make_engine,
        hatch,
        5000.0,
        [PhysicsFault(kind="wastegate_stuck", stuck_position_pct=100.0)],
        seconds=3.0,
        duty=duty,
    )
    assert state.boost_pre_throttle_kpa - 99.0 <= 50.0 + 10.0
    assert state.wastegate_position_pct == 100.0
