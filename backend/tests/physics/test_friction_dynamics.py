"""Chen-Flynn, torque de freio, potência na roda e dinâmica rotacional (T098; RF-11, RF-21)."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from simremap.catalog.contracts import ChenFlynnSpec, VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.friction import (
    brake_torque_nm,
    chen_flynn_fmep_kpa,
    engine_inertia_kg_m2,
    imep_kpa,
    pmep_kpa,
    power_kw,
    rpm_rate_per_s,
    wheel_power_kw,
    whp,
)
from simremap.physics.reference import ReferenceDriver, RpmHoldRig, free_load


def test_chen_flynn_formula() -> None:
    spec = ChenFlynnSpec()
    # p_max 80 bar, S̄p 15 m/s: 0,25 + 0,005·80 + 0,09·15 + 0,0009·225 = 2,2025 bar.
    assert chen_flynn_fmep_kpa(spec, 8000.0, 15.0) == pytest.approx(220.25)
    custom = ChenFlynnSpec(c_bar=0.3, a=0.0, b_bar_s_m=0.0, q_bar_s2_m2=0.0)
    assert chen_flynn_fmep_kpa(custom, 1e4, 20.0) == pytest.approx(30.0)


def test_brake_torque_formula_appendix_a6() -> None:
    """RF-11: T_b = (IMEP − PMEP − FMEP)·1000·V_d/(4π) − P_sc·1000/ω, erro < 0,1 %."""
    vd = 1.9843e-3
    imep, pmep, fmep = 2200.0, -30.0, 210.0
    expected = (imep - pmep - fmep) * 1000 * vd / (4 * math.pi)
    assert brake_torque_nm(imep, pmep, fmep, vd) == pytest.approx(expected, rel=1e-3)
    omega = 2 * math.pi * 6000 / 60
    with_sc = brake_torque_nm(imep, pmep, fmep, vd, 60.0, omega)
    assert with_sc == pytest.approx(expected - 60e3 / omega, rel=1e-3)
    assert imep_kpa(1100.0, 4.96e-4) == pytest.approx(1100 / 4.96e-4 / 1000)
    assert pmep_kpa(250.0, 230.0) == 20.0


def test_power_and_wheel_power() -> None:
    p = power_kw(307.3, 6000.0)
    assert p == pytest.approx(193.1, abs=0.1)
    wheel = wheel_power_kw(p, 0.85, 0.0)
    assert wheel == pytest.approx(p * 0.85)
    assert whp(wheel) == pytest.approx(220.1, abs=0.2)
    assert wheel_power_kw(100.0, 0.9, 5.0) == pytest.approx(85.0)


def test_rotational_dynamics_rate() -> None:
    """RF-21: T_load = 0, J 0,25 kg·m², T_b 100 N·m ⇒ +3820 rpm/s ± 1 %."""
    assert rpm_rate_per_s(100.0, 0.25) == pytest.approx(3820.0, rel=0.01)
    assert engine_inertia_kg_m2(1984) == pytest.approx(0.05 + 0.055 * 1.984)


def test_engine_integrates_rotational_dynamics(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """No motor, Δrpm por tick = (T_b − T_load)/(J_eng + J_refl) com J total 0,25 kg·m²."""
    engine = make_engine(hatch, noise_enabled=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=40.0)
    rig = RpmHoldRig(target_rpm=3000.0)
    engine.crank(3000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(500):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    j_refl = 0.25 - engine.j_engine
    load = free_load(inertia_kg_m2=j_refl, torque_nm=20.0)
    for _ in range(50):
        rpm0 = engine.rpm
        state = engine.step(driver.commands(engine.read_sensors(), dt), load, dt)
        expected = rpm0 + rpm_rate_per_s(state.torque_nm - 20.0, 0.25) * dt
        assert engine.rpm == pytest.approx(expected, rel=1e-12)
    assert state is not None
    assert state.power_kw == pytest.approx(power_kw(state.torque_nm, rpm0))
    assert state.wheel_power_kw == pytest.approx(state.power_kw * 0.85)
    assert state.whp == pytest.approx(state.wheel_power_kw / 0.7457)
    brake = brake_torque_nm(
        state.imep_gross_kpa, state.pmep_kpa, state.fmep_kpa, engine.geo.vd_total_m3
    )
    assert state.torque_nm == pytest.approx(brake, rel=1e-9)


def test_overrev_saturates(make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec) -> None:
    """EC-07: rpm acima de max_rpm · 1,15 é saturado."""
    engine = make_engine(hatch, noise_enabled=False)
    engine.crank(1e5)
    assert engine.rpm == pytest.approx(6800 * 1.15)


def test_stall_below_300_rpm(make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec) -> None:
    """EC-06: abaixo de 300 rpm sem motor de arranque ⇒ stalled e rpm 0."""
    engine = make_engine(hatch, noise_enabled=False)
    engine.crank(600.0)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=0.0)
    driver.fuel_cut = [True] * 4
    dt = engine.resolved.dt
    state = None
    for _ in range(3000):
        state = engine.step(driver.commands(None, dt), free_load(torque_nm=30.0), dt)
        if state.stalled:
            break
    assert state is not None and state.stalled
    assert state.rpm == 0.0
    # Motor de arranque: segura 250 rpm sem marcar stall.
    engine.crank()
    state = engine.step(driver.commands(None, dt), free_load(torque_nm=0.0), dt)
    assert not state.stalled
    assert state.rpm == pytest.approx(250.0)
