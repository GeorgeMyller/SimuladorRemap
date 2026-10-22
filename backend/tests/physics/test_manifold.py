"""Coletor de admissão filling & emptying (T094; physics RF-04, RNF-04)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.fuel import R_AIR
from simremap.physics.manifold import (
    linear_implicit_step,
    orifice_flow,
    psi,
    throttle_area_m2,
    volume_rate_kpa_s,
)
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


def test_psi_choked_and_limits() -> None:
    choked = math.sqrt(1.4) * (2 / 2.4) ** (2.4 / 0.8)
    assert psi(0.1) == pytest.approx(choked)
    assert psi(0.5) == pytest.approx(choked)  # abaixo de 0,528 o escoamento bloqueia
    assert psi(1.0) == 0.0
    assert psi(1.2) == 0.0
    # Subsónico: fórmula fechada de A.2.
    pr = 0.8
    expected = math.sqrt(2 * 1.4 / 0.4 * (pr ** (2 / 1.4) - pr ** (2.4 / 1.4)))
    assert psi(pr) == pytest.approx(expected)
    # Regularização linear perto de 1: contínua em 0,98 e monótona.
    assert psi(0.98) == pytest.approx(psi(0.9799999), rel=1e-4)
    assert psi(0.99) == pytest.approx(psi(0.98) / 2, rel=1e-9)


def test_orifice_flow_sign_and_magnitude() -> None:
    area = 1e-3
    fwd = orifice_flow(area, 200.0, 300.0, 100.0, 300.0)
    rev = orifice_flow(area, 100.0, 300.0, 200.0, 300.0)
    assert fwd > 0.0
    assert rev == pytest.approx(-fwd)
    assert orifice_flow(0.0, 200.0, 300.0, 100.0, 300.0) == 0.0
    # Bloqueado: ṁ = A · p · Ψ* / √(R T).
    m = orifice_flow(area, 300.0, 300.0, 100.0, 300.0)
    assert m == pytest.approx(area * 300e3 / math.sqrt(R_AIR * 300.0) * psi(0.3), rel=1e-3)


def test_throttle_area_law() -> None:
    d = 0.056
    a_max = math.pi / 4 * d * d
    assert throttle_area_m2(0.0, d) == pytest.approx(0.004 * a_max)
    assert throttle_area_m2(100.0, d) == pytest.approx(a_max)
    assert throttle_area_m2(50.0, d) == pytest.approx(
        0.004 * a_max + 0.996 * a_max * (1 - math.cos(math.pi / 4))
    )
    assert throttle_area_m2(150.0, d) == throttle_area_m2(100.0, d)


def test_volume_rate() -> None:
    # 1 g/s num volume de 3 L a 300 K: dp/dt = R·T/V · ṁ / 1000 (kPa/s).
    assert volume_rate_kpa_s(287.05, 300.0, 3e-3, 1e-3) == pytest.approx(28.705)


def test_linear_implicit_step_is_stable_on_stiff_system() -> None:
    """Sistema linear rígido (λ·h = −50): o passo implícito converge sem oscilar."""
    lam = -5.0e4

    def rates(x: Sequence[float]) -> list[float]:
        return [lam * (x[0] - 10.0), -50.0 * (x[1] - x[0])]

    x = [0.0, 0.0]
    for _ in range(200):
        x = linear_implicit_step(rates, x, 1e-3)
        assert x[0] <= 10.0 + 1e-6
    assert x[0] == pytest.approx(10.0, rel=1e-9)
    assert x[1] == pytest.approx(10.0, rel=1e-3)
    assert linear_implicit_step(rates, [], 1e-3) == []


def _run_na(
    engine: PhysicsEngine,
    driver: ReferenceDriver,
    rig: RpmHoldRig,
    ticks: int,
    record: list[float] | None = None,
) -> None:
    dt = engine.resolved.dt
    state = None
    for _ in range(ticks):
        sensors = engine.read_sensors()
        state = engine.step(driver.commands(sensors, dt), rig.load(state, engine.rpm, dt), dt)
        if record is not None:
            record.append(state.map_kpa)


def test_throttle_step_map_response_time(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    """RF-04: degrau 10 % → 100 % a 3000 rpm aspirado: 90 % do MAP final em 30–150 ms."""
    engine = make_engine(na_vehicle, noise_enabled=False)
    driver = ReferenceDriver(engine, na_vehicle.reference_command_schedule, throttle_pct=10.0)
    rig = RpmHoldRig(target_rpm=3000.0, inertia_kg_m2=1e4)
    engine.crank(3000.0)
    _run_na(engine, driver, rig, 3000)
    map0 = engine.vars.p_man_kpa
    driver.throttle_override = 100.0
    trace: list[float] = []
    _run_na(engine, driver, rig, 1500, trace)
    final = trace[-1]
    assert final > map0 + 30.0
    target = map0 + 0.9 * (final - map0)
    t90 = next(i for i, p in enumerate(trace) if p >= target) * engine.resolved.dt
    assert 0.030 <= t90 <= 0.150


def test_manifold_mass_conservation_60s(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    """RF-04/RNF-04: ar pela borboleta = ar aprisionado + Δ armazenado (erro < 0,1 % em 60 s)."""
    engine = make_engine(na_vehicle, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, na_vehicle.reference_command_schedule, throttle_pct=35.0)
    rig = RpmHoldRig(target_rpm=3000.0, inertia_kg_m2=1e4)
    engine.crank(3000.0)
    _run_na(engine, driver, rig, 1500)  # regime
    v = engine.vars
    thr0, trap0 = v.m_throttle_cum_kg, v.m_trapped_cum_kg
    m_man0 = v.p_man_kpa * 1000 * engine.v_man / (R_AIR * v.t_man_k)
    _run_na(engine, driver, rig, 60 * 500)
    m_man1 = v.p_man_kpa * 1000 * engine.v_man / (R_AIR * v.t_man_k)
    inflow = v.m_throttle_cum_kg - thr0
    outflow = v.m_trapped_cum_kg - trap0
    assert inflow > 1.0  # kg em 60 s
    err = abs(inflow - outflow - (m_man1 - m_man0)) / inflow
    assert err < 1e-3
