"""EGT, cortes e pós-combustão (T099; physics RF-13, RF-22)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import CombustionEvent
from simremap.physics.engine import PhysicsEngine
from simremap.physics.exhaust import (
    PORT_EFFECTIVENESS,
    PORT_GAS_MAX_K,
    PORT_WALL_ABOVE_ECT_K,
    blowdown_temperature,
    exhaust_event,
    first_order,
    manifold_heat_loss,
)
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


def _hold(
    engine: PhysicsEngine, driver: ReferenceDriver, rpm: float, seconds: float, avg_s: float = 0.3
) -> tuple[float, float]:
    """Média de (torque, EGT média dos cilindros) no último ``avg_s``."""
    dt = engine.resolved.dt
    rig = RpmHoldRig(target_rpm=rpm, inertia_kg_m2=1e4)
    n = round(seconds / dt)
    navg = round(avg_s / dt)
    tq = egt = 0.0
    state = None
    for k in range(n):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
        if k >= n - navg:
            tq += state.torque_nm
            egt += sum(state.egt_c) / len(state.egt_c)
    return tq / navg, egt / navg


def test_blowdown_and_port_helpers() -> None:
    assert blowdown_temperature(1500.0, 300.0, 400.0) == 1500.0
    t_bd = blowdown_temperature(1500.0, 600.0, 200.0)
    assert 1100.0 < t_bd < 1500.0
    ev = exhaust_event(1500.0, 600.0, 200.0, 1e-3, 0.0, 0.0, False, 90.0)
    assert ev.afterfire_energy_j == 0.0 and not ev.pop_event
    assert ev.t_port_k < t_bd
    burn = exhaust_event(1500.0, 600.0, 200.0, 1e-3, 1000.0, 0.0, True, 90.0)
    assert burn.afterfire_energy_j == pytest.approx(600.0)
    assert burn.t_port_k > ev.t_port_k and burn.pop_event
    rich = exhaust_event(1500.0, 600.0, 200.0, 1e-3, 0.0, 500.0, False, 90.0)
    assert rich.t_port_k < ev.t_port_k
    assert first_order(0.0, 1.0, 0.1, 0.1) == pytest.approx(1 - 1 / 2.718281828, rel=1e-6)
    assert manifold_heat_loss(1200.0, 0.0, 25.0, 90.0) == 1200.0
    assert manifold_heat_loss(1200.0, 0.05, 25.0, 90.0) < manifold_heat_loss(
        1200.0, 0.2, 25.0, 90.0
    )


def test_retard_from_mbt_raises_egt(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-13: atrasar 10° a partir do MBT eleva a EGT de regime ≥ 40 °C (gás na porta)."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(
        engine, hatch.reference_command_schedule, lambda_target=0.85, advance_deg=30.0
    )
    engine.crank(3000.0)
    _hold(engine, driver, 3000.0, 5.0)
    best = (-1.0, 0.0, 0.0)
    for adv in range(24, 40, 2):
        driver.advance_override = float(adv)
        tq, egt = _hold(engine, driver, 3000.0, 1.5)
        if tq > best[1]:
            best = (float(adv), tq, egt)
    mbt, _, _ = best
    driver.advance_override = mbt
    _, egt_mbt = _hold(engine, driver, 3000.0, 4.0)
    driver.advance_override = mbt - 10.0
    _, egt_retard = _hold(engine, driver, 3000.0, 4.0)
    assert egt_retard - egt_mbt >= 40.0


def test_rich_mixture_lowers_egt(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-13: λ 0,80 reduz a EGT ≥ 30 °C face a λ 0,90 no mesmo ponto."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, lambda_target=0.90)
    engine.crank(4000.0)
    _, egt_90 = _hold(engine, driver, 4000.0, 6.0)
    driver.lambda_override = 0.80
    _, egt_80 = _hold(engine, driver, 4000.0, 4.0)
    assert egt_90 - egt_80 >= 30.0


def test_spark_cut_with_fuel_pops(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-22: corte de ignição com injeção ⇒ afterfire_energy_j > 0 e pop_event."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=1000)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=40.0)
    rig = RpmHoldRig(target_rpm=4000.0, inertia_kg_m2=1e4)
    engine.crank(4000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(1000):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    driver.spark_cut = [False, True, False, False]
    cut_events: list[CombustionEvent] = []
    other: list[CombustionEvent] = []
    for _ in range(200):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
        for ev in state.events:
            (cut_events if ev.cylinder == 2 else other).append(ev)
    assert cut_events
    assert all(ev.misfire and ev.afterfire_energy_j > 0.0 and ev.pop_event for ev in cut_events)
    assert all(ev.lambda_real is not None for ev in cut_events)
    assert not any(ev.misfire for ev in other)


def test_fuel_cut_lambda_none_and_egt_falls(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-22: corte de combustível ⇒ λ do cilindro None e EGT descendente."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=1000)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=40.0)
    rig = RpmHoldRig(target_rpm=3000.0, inertia_kg_m2=1e4)
    engine.crank(3000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(1500):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None
    egt0 = state.egt_c[0]
    driver.fuel_cut = [True] * 4
    events = []
    for _ in range(800):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
        events.extend(state.events)
    assert all(ev.lambda_real is None and not ev.misfire for ev in events)
    assert state.lambda_cyl == [None] * 4
    assert state.lambda_collector is None
    assert state.egt_c[0] < egt0 - 200.0
    assert state.fuel_flow_g_s == 0.0


def test_port_gas_capped_at_adiabatic_temperature() -> None:
    """Massa de escape ínfima com energia química: o gás na porta fica em ≤ 2400 K."""
    ev = exhaust_event(1500.0, 600.0, 200.0, 1e-7, 5000.0, 0.0, True, 90.0)
    t_wall = 90.0 + 273.15 + PORT_WALL_ABOVE_ECT_K
    assert ev.t_port_k == pytest.approx(t_wall + (PORT_GAS_MAX_K - t_wall) * PORT_EFFECTIVENESS)


def test_cylinder_egt_probe_tracks_flow(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """``egt_c`` na sonda do runner: em marcha lenta tende à parede; em carga ≈ gás da porta."""
    from simremap.physics.contracts import ActuatorCommands
    from simremap.physics.reference import free_load

    engine = make_engine(hatch)
    engine.crank(900.0)
    dt = engine.resolved.dt
    n = hatch.engine.n_cyl
    cmd = ActuatorCommands(
        t_sim_s=0.0,
        injector_pw_ms=[0.9] * n,
        injection_end_deg_btdc=None,
        ignition_advance_deg=[5.0] * n,
        fuel_cut=[False] * n,
        spark_cut=[False] * n,
        throttle_pct=0.0,
        wastegate_duty_pct=0.0,
        vvt_intake_target_deg=0.0,
        vvt_exhaust_target_deg=0.0,
        bypass_open=False,
        antilag_air_pct=0.0,
        fuel_pump_duty_pct=100.0,
    )
    state = None
    for _ in range(round(2.0 / dt)):
        state = engine.step(cmd, free_load(inertia_kg_m2=0.0), dt)
    assert state is not None and state.rpm > 300.0
    port_c = [t - 273.15 for t in engine.vars.egt_gas_k]
    assert all(probe < port - 100.0 for probe, port in zip(state.egt_c, port_c, strict=True))
    assert all(probe < 800.0 for probe in state.egt_c)
