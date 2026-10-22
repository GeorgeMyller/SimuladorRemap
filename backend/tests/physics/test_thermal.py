"""Temperaturas lumpadas (ECT, pistão, ponto quente), heat soak e pressão de óleo (T102; RF-24)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import EngineState
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig
from simremap.physics.thermal import (
    CoolantModel,
    hot_spot_target_c,
    oil_pressure_kpa,
    oil_temp_rate,
    piston_target_c,
    relax,
)


def test_first_order_helpers() -> None:
    assert relax(0.0, 10.0, 1.0, 1e9) == pytest.approx(0.0, abs=1e-6)
    assert relax(0.0, 10.0, 100.0, 1.0) == pytest.approx(10.0)
    assert piston_target_c(90.0, 0.0) == 90.0
    assert piston_target_c(90.0, 15_000.0) == pytest.approx(90.0 + 0.3 * 15_000 / 45.0)
    assert hot_spot_target_c(90.0, 900.0, True) == pytest.approx(90 + 0.75 * 810)
    assert hot_spot_target_c(90.0, 900.0, False) == 90.0
    assert oil_temp_rate(80.0, 90.0, 0.0) == pytest.approx(10.0 / 90.0)


def test_oil_pressure_model() -> None:
    """T251 (D-BUS-03): 0 parado/bloqueado, cresce com rpm, alívio a 550 kPa, viscosidade."""
    assert oil_pressure_kpa(0.0, 90.0, False) == 0.0
    assert oil_pressure_kpa(3000.0, 90.0, True) == 0.0
    idle = oil_pressure_kpa(800.0, 90.0, False)
    assert idle == pytest.approx(60 + 0.085 * 800)
    assert oil_pressure_kpa(3000.0, 90.0, False) > idle
    assert oil_pressure_kpa(9000.0, 90.0, False) == pytest.approx(550.0)
    assert oil_pressure_kpa(2000.0, 20.0, False) > oil_pressure_kpa(2000.0, 120.0, False)
    assert oil_pressure_kpa(200.0, 90.0, False) == pytest.approx((60 + 17) * 0.5)


def test_coolant_thermostat() -> None:
    cm = CoolantModel()
    cold = cm.rate(40.0, 20_000.0, 25.0, 15.0)
    hot = cm.rate(100.0, 20_000.0, 25.0, 15.0)
    assert cold > 0.0 > hot  # termóstato abre acima de 88 °C


def _drive(
    engine: PhysicsEngine,
    driver: ReferenceDriver,
    rig: RpmHoldRig,
    seconds: float,
    ramp: tuple[float, float] | None = None,
) -> EngineState:
    dt = engine.resolved.dt
    n = round(seconds / dt)
    state = None
    for k in range(n):
        if ramp is not None:
            rig.target_rpm = ramp[0] + (ramp[1] - ramp[0]) * k / (n - 1)
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None
    return state


def test_heat_soak_between_pulls_and_recovery(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-24: 5 puxadas WOT seguidas elevam a IAT ≥ 5 °C; 120 s de marcha lenta repõem ± 2 °C."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=200)
    idle = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=3.0)
    wot = ReferenceDriver(engine, hatch.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=900.0)
    engine.crank(900.0)
    _drive(engine, idle, rig, 30.0)
    iat_idle0 = engine.vars.t_man_k
    iat_at_4000: list[float] = []
    for _ in range(5):
        rig.target_rpm = 3000.0
        _drive(engine, wot, rig, 2.0)
        state = _drive(engine, wot, rig, 6.0, ramp=(3000.0, 5000.0))
        iat_at_4000.append(state.iat_c)
        _drive(engine, wot, rig, 2.0, ramp=(5000.0, 3000.0))
    assert iat_at_4000[-1] - iat_at_4000[0] >= 5.0
    rig.target_rpm = 900.0
    _drive(engine, idle, rig, 120.0)
    assert abs(engine.vars.t_man_k - iat_idle0) <= 2.0


def test_ect_piston_and_hot_spot_respond_to_load(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    engine = make_engine(hatch, noise_enabled=False, sim_hz=200, warm=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    rig = RpmHoldRig(target_rpm=5000.0)
    engine.crank(5000.0)
    ect0 = engine.vars.ect_c
    state = _drive(engine, driver, rig, 20.0)
    assert state.ect_c > ect0 + 5.0
    assert all(p > state.ect_c + 30.0 for p in state.piston_temp_c)
    assert all(h > p for h, p in zip(state.hot_spot_temp_c, state.piston_temp_c, strict=True))
    assert engine.read_sensors().oil_pressure_kpa > 300.0
