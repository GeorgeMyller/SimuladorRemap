"""Supercharger de deslocamento positivo (T101; physics RF-15)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver, RpmHoldRig
from simremap.physics.supercharger import SuperchargerModel


def test_supercharger_model_equations(muscle: VehicleSpec) -> None:
    assert muscle.supercharger is not None
    sc = SuperchargerModel(muscle.supercharger)
    assert sc.rotor_rpm(6000.0) == pytest.approx(11_400.0)
    assert sc.volumetric_efficiency(1.0, 11_400.0) == pytest.approx(0.98)  # saturação
    assert sc.volumetric_efficiency(2.0, 11_400.0) == pytest.approx(1 - 0.08 * 10_000 / 11_400)
    assert sc.volumetric_efficiency(3.0, 1000.0) == pytest.approx(0.5)
    assert sc.volumetric_efficiency(2.0, 0.0) == pytest.approx(0.5)
    point = sc.operate(6000.0, 100.0, 298.15, 200.0)
    rho = 100e3 / (287.05 * 298.15)
    eta_v = 1 - 0.08 * 1.0 * 10_000 / 11_400
    assert point.mass_flow_kg_s == pytest.approx(rho * 2.65e-3 * 11_400 / 60 * eta_v)
    assert point.adiabatic_efficiency == pytest.approx(0.64)
    t_out = 298.15 * (1 + (2.0 ** (0.4 / 1.4) - 1) / 0.64)
    assert point.t_out_k == pytest.approx(t_out)
    assert point.power_kw == pytest.approx(
        point.mass_flow_kg_s * 1005 * (t_out - 298.15) / 0.90 / 1000
    )


def _run(engine: PhysicsEngine, driver: ReferenceDriver, rpm: float, ticks: int) -> float:
    rig = RpmHoldRig(target_rpm=rpm)
    dt = engine.resolved.dt
    state = None
    for _ in range(ticks):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None and state.supercharger_power_kw is not None
    assert state.supercharger_rpm == pytest.approx(rpm * 1.90, rel=1e-3)
    return state.supercharger_power_kw


def test_parasitic_loss_and_bypass(
    make_engine: Callable[..., PhysicsEngine], muscle: VehicleSpec
) -> None:
    """RF-15: muscle-v8-sc a 6000 rpm WOT ⇒ perda 40–80 kW; bypass aberto ⇒ queda ≥ 80 %."""
    engine = make_engine(muscle, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, muscle.reference_command_schedule)
    engine.crank(6000.0)
    loss = _run(engine, driver, 6000.0, 1500)
    assert 40.0 <= loss <= 80.0
    map_closed = engine.vars.p_man_kpa
    driver.bypass_open = True
    loss_open = _run(engine, driver, 6000.0, 1000)
    assert loss_open <= 0.2 * loss
    assert engine.vars.p_man_kpa < map_closed - 50.0
    # Com bypass aberto a razão de pressão cai para ≈ 1,0–1,1.
    assert engine.vars.p_man_kpa / engine.vars.p_boost_kpa < 1.1


def test_pre_compressor_throttle_controls_flow(
    make_engine: Callable[..., PhysicsEngine], muscle: VehicleSpec
) -> None:
    """Borboleta antes do compressor: fechar a borboleta reduz o MAP e a perda."""
    engine = make_engine(muscle, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, muscle.reference_command_schedule, throttle_pct=15.0)
    engine.crank(3000.0)
    loss = _run(engine, driver, 3000.0, 1500)
    part_map = engine.vars.p_man_kpa
    driver.throttle_override = 100.0
    loss_wot = _run(engine, driver, 3000.0, 1500)
    assert engine.vars.p_man_kpa > part_map + 50.0
    assert loss_wot > loss
    assert engine.read_sensors().boost_pre_throttle_kpa == pytest.approx(engine.vars.p_amb_kpa)
