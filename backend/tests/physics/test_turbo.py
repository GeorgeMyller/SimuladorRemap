"""Turbo: eixo com inércia, mapas, wastegate e intercooler (T100; physics RF-14, EC-08)."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from simremap.catalog.contracts import IntercoolerSpec, VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import (
    ReferenceDriver,
    RpmHoldRig,
    free_load,
    interpolate_schedule,
)
from simremap.physics.turbo import (
    CompressorMap,
    IntercoolerModel,
    TurbineModel,
    rad_s_to_rpm,
    rpm_to_rad_s,
    shaft_acceleration,
    wastegate_target,
)


def test_compressor_speed_line(hatch: VehicleSpec) -> None:
    assert hatch.turbo is not None
    cmap = CompressorMap(hatch.turbo.compressor)
    spec = hatch.turbo.compressor
    m, m_choke, pr0 = cmap.corrected_flow(1.0, spec.n_design_rpm)
    assert m == m_choke == pytest.approx(spec.m_choke_max_kg_s * (200 / 220) ** 0.8)
    assert pr0 == pytest.approx(spec.pr_design)
    assert cmap.corrected_flow(pr0, spec.n_design_rpm)[0] == 0.0
    mid = cmap.corrected_flow(1.0 + 0.5 * (pr0 - 1.0), spec.n_design_rpm)[0]
    assert mid == pytest.approx(m_choke * math.sqrt(0.75))
    assert cmap.corrected_flow(1.5, 0.0)[0] == 0.0
    # Eficiência máxima no pico e saturação inferior.
    assert cmap.efficiency(spec.m_peak_kg_s, spec.n_peak_rpm) == pytest.approx(spec.eta_max)
    assert cmap.efficiency(0.0, 20_000) == pytest.approx(0.45)
    assert cmap.efficiency(spec.m_peak_kg_s, 1.2 * spec.n_max_rpm) < 0.45  # sobrevelocidade
    point = cmap.operate(2.0, 180_000, 99.0, 298.15)
    assert point.t_out_k > 298.15 * 2.0 ** (0.4 / 1.4)
    assert point.power_w == pytest.approx(point.mass_flow_kg_s * 1005 * (point.t_out_k - 298.15))
    surge = cmap.operate(pr0 * 0.999, spec.n_design_rpm, 101.325, 298.15)
    assert surge.surge_margin < 0.0


def test_surge_line_recedes_at_low_speed(hatch: VehicleSpec) -> None:
    """T033 (B4): a plena carga a baixa rotação (topo da linha, PR 1,1–1,5) não é surge."""
    assert hatch.turbo is not None
    cmap = CompressorMap(hatch.turbo.compressor)
    spec = hatch.turbo.compressor
    for frac in (0.25, 0.5):  # N / N_design
        n = frac * spec.n_design_rpm
        pr0 = cmap.corrected_flow(1.0, n)[2]
        y = 0.96  # ṁ = 0,28 · ṁ_choke(N): era surge com a fração fixa de 0,30
        point = cmap.operate(1.0 + y * (pr0 - 1.0), n, 101.325, 298.15)
        assert point.surge_margin > 0.0
    # Sem elevação de pressão que sustente a reversão, o fluxo nulo não é surge.
    assert cmap.operate(1.04, 0.15 * spec.n_design_rpm, 101.325, 298.15).surge_margin == 1.0


def test_turbine_and_wastegate(hatch: VehicleSpec) -> None:
    assert hatch.turbo is not None
    turb = TurbineModel(hatch.turbo)
    assert turb.flow(100.0, 1100.0, 100.0) == 0.0
    m1 = turb.flow(200.0, 1100.0, 100.0)
    m2 = turb.flow(300.0, 1100.0, 100.0)
    assert m2 > m1 > 0.0
    assert turb.power_w(m2, 300.0, 1100.0, 100.0) > turb.power_w(m1, 200.0, 1100.0, 100.0) > 0
    assert turb.wastegate_flow(0.0, 300.0, 1100.0, 100.0) == 0.0
    assert turb.wastegate_flow(1.0, 300.0, 1100.0, 100.0) > 0.0
    # x_wg = clip((p_rel·(1 − duty) − mola) / Δp_full, 0, 1).
    assert wastegate_target(160.0, 100.0, 0.0, 50.0, 8.0) == pytest.approx(1.0)
    assert wastegate_target(154.0, 100.0, 0.0, 50.0, 8.0) == pytest.approx(0.5)
    assert wastegate_target(154.0, 100.0, 50.0, 50.0, 8.0) == 0.0


def test_shaft_and_intercooler() -> None:
    assert rad_s_to_rpm(rpm_to_rad_s(150_000.0)) == pytest.approx(150_000.0)
    omega = rpm_to_rad_s(150_000)
    acc = shaft_acceleration(omega, 10_000.0, 8_000.0, 2e-5, 4e-7)
    assert acc == pytest.approx(2000.0 / (2e-5 * omega) - 4e-7 * omega / 2e-5)
    assert shaft_acceleration(0.0, 100.0, 0.0, 2e-5, 0.0) == pytest.approx(100.0 / (2e-5 * 500))
    ic = IntercoolerModel(
        IntercoolerSpec(kind="air_to_air", effectiveness=0.75, k_dp_kpa_per_kgps2=100.0)
    )
    assert ic.outlet_temp(400.0, 300.0) == pytest.approx(325.0)
    assert ic.pressure_drop_kpa(0.2) == pytest.approx(4.0)
    assert ic.core_rate(300.0, 400.0, 0.2, 300.0, 15.0) > 0.0
    none = IntercoolerModel(None)
    assert none.outlet_temp(400.0, 300.0) == 400.0
    assert none.core_rate(300.0, 400.0, 0.2, 300.0, 15.0) == 0.0


def test_spool_2000_rpm_third_gear(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-14: WOT a 2000 rpm em 3.ª ⇒ boost a 90 % do alvo em 0,8–2,5 s.

    3.ª marcha num rolo inercial: J refletido ≈ 2,9 kg·m² na cambota (rolo de 300 kg·m² e
    transmissão 1,30 × 4,12), partindo de cruzeiro a 15 % de borboleta.
    """
    engine = make_engine(hatch, noise_enabled=False)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule, throttle_pct=15.0)
    rig = RpmHoldRig(target_rpm=2000.0)
    engine.crank(2000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(5000):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    driver.throttle_override = None
    load = free_load(inertia_kg_m2=2.9, torque_nm=40.0)
    t90 = None
    for k in range(4000):
        state = engine.step(driver.commands(engine.read_sensors(), dt), load, dt)
        target = interpolate_schedule(hatch.reference_command_schedule, engine.rpm).map_target_kpa
        if state.map_kpa >= 0.9 * target:
            t90 = (k + 1) * dt
            break
    assert t90 is not None
    assert 0.8 <= t90 <= 2.5


def test_zero_duty_holds_spring_pressure(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-14: duty 0 % mantém o boost na pressão de mola ± 5 kPa."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    driver.duty_override = 0.0
    rig = RpmHoldRig(target_rpm=4000.0)
    engine.crank(4000.0)
    dt = engine.resolved.dt
    state = None
    for _ in range(2500):
        state = engine.step(
            driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
        )
    assert state is not None and state.wastegate_position_pct is not None
    gauge = state.boost_pre_throttle_kpa - 99.0
    assert gauge == pytest.approx(50.0, abs=5.0)
    assert 0.0 < state.wastegate_position_pct < 100.0
    assert state.turbo_rpm is not None and state.turbo_rpm > 100_000
    assert state.compressor_pressure_ratio is not None and state.compressor_pressure_ratio > 1.4
    assert state.t_intercooler_out_c is not None and state.t_intercooler_out_c < 80.0


def test_blow_off_valve_and_surge_oscillation(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """Corte de borboleta em boost: BOV alivia; sem BOV entra em surge (EC-08) sem exceção."""
    margins = {}
    for bov in (True, False):
        engine = make_engine(hatch, noise_enabled=False)
        driver = ReferenceDriver(engine, hatch.reference_command_schedule)
        rig = RpmHoldRig(target_rpm=4000.0)
        engine.crank(4000.0)
        dt = engine.resolved.dt
        state = None
        for _ in range(4000):
            state = engine.step(
                driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
            )
        driver.throttle_override = 0.0
        driver.bypass_open = bov
        worst = 1.0
        for _ in range(300):
            state = engine.step(
                driver.commands(engine.read_sensors(), dt), rig.load(state, engine.rpm, dt), dt
            )
            assert state.surge_margin is not None
            worst = min(worst, state.surge_margin)
        margins[bov] = worst
        if not bov:
            assert engine.vars.surge_s > 0.0
    assert margins[False] < 0.0
    assert margins[True] > margins[False]
