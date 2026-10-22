"""Ciclo de zona única, Woschni, MBT emergente e cache (T097; RF-03, RF-10, RF-12, RF-18)."""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.physics.cycle_solver import (
    CycleSolver,
    gamma_of_t,
    internal_energy_per_kg,
    quantize_inputs,
)
from simremap.physics.engine import PhysicsEngine
from simremap.physics.geometry import CylinderGeometry
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


@pytest.fixture
def solver(hatch: VehicleSpec, fuels: dict[str, FuelSpec]) -> tuple[CycleSolver, int]:
    geo = CylinderGeometry.from_engine(hatch.engine)
    s = CycleSolver(geo, hatch.engine, 5.0, 2.0, 16)
    return s, s.register_fuel(fuels["e27"])


def test_gamma_and_internal_energy() -> None:
    assert gamma_of_t(300.0) == pytest.approx(1.392 - 8.13e-5 * 300)
    assert gamma_of_t(0.0) == pytest.approx(1.392)
    assert gamma_of_t(5000.0) == 1.20
    # cv = du/dT = R / (γ − 1) nos dois ramos.
    for t in (400.0, 1500.0, 3000.0):
        cv = (internal_energy_per_kg(t + 0.5) - internal_energy_per_kg(t - 0.5)) / 1.0
        assert cv == pytest.approx(287.0 / (gamma_of_t(t) - 1.0), rel=1e-4)


def test_motored_cycle_peak_and_energy(solver: tuple[CycleSolver, int]) -> None:
    """RF-10: ciclo motorizado a 2000 rpm ⇒ p_max ∈ [0,80; 1,00]·p_ivc·r_c^1,30; balanço ≤ 2 %."""
    s, fi = solver
    _, inp = quantize_inputs(2000, 0.15e-3, 1.0, 0.10, 370.0, 20.0, -140, 135, 373.0, False, fi)
    res = s.solve_uncached(inp)
    ratio = res.p_max_pa / (res.pressure_pa[0] * 9.6**1.30)
    assert 0.80 <= ratio <= 1.00
    assert res.energy_error <= 0.02
    assert res.q_comb_j == 0.0
    assert abs(res.theta_pmax_deg) < 2.0  # pico motorizado junto ao PMS
    assert len(res.pressure_pa) == (135 - (-140)) + 1


def test_fired_cycle_energy_balance_and_traces(solver: tuple[CycleSolver, int]) -> None:
    s, fi = solver
    key, inp = quantize_inputs(3000, 1.15e-3, 0.85, 0.04, 330.0, 28.0, -140, 135, 453.0, True, fi)
    res = s.solve(key, inp)
    assert res.energy_error <= 0.02
    assert res.q_comb_j > 0.9 * 0.98 * res.q_available_j
    assert res.work_j > 0.0 and res.q_wall_j > 0.0
    n = len(res.event_pressure_kpa)
    assert n == len(res.event_t_unburned_k) == len(res.event_burned_fraction) > 10
    assert res.event_theta_start == math.ceil(-28.0)
    assert res.event_burned_fraction[-1] >= 0.99
    assert res.t_unburned_max_k == pytest.approx(max(res.event_t_unburned_k))
    assert res.p_max_pa / 1000.0 == pytest.approx(max(res.event_pressure_kpa), rel=1e-12)
    assert res.unburned_chem_j > 0.0  # λ 0,85: excesso de combustível segue para o escape


def test_cache_hit_returns_identical_result(solver: tuple[CycleSolver, int]) -> None:
    s, fi = solver
    k1, i1 = quantize_inputs(
        3000.4, 1.150e-3, 0.8501, 0.0401, 330.2, 28.05, -140, 135, 453.3, True, fi
    )
    k2, i2 = quantize_inputs(
        3001.0, 1.1501e-3, 0.8504, 0.0402, 329.9, 27.95, -140, 135, 453.1, True, fi
    )
    assert k1 == k2 and i1 == i2  # mesma célula de quantização
    first = s.solve(k1, i1)
    second = s.solve(k2, i2)
    assert second is first
    assert s.hits == 1
    assert s.solve_uncached(i2) == first


def test_lru_eviction(solver: tuple[CycleSolver, int]) -> None:
    s, fi = solver  # cache de 16 entradas
    for rpm in range(1000, 1000 + 20 * 50, 50):
        key, inp = quantize_inputs(rpm, 0.5e-3, 1.0, 0.05, 330, 20, -140, 135, 450, True, fi)
        s.solve(key, inp)
    assert s.cache_len() == 16
    s.clear_cache()
    assert s.cache_len() == 0


def test_livengood_wu_hook_matches_full_trace(solver: tuple[CycleSolver, int]) -> None:
    """RF-18: a integral de Livengood-Wu sobre o histórico do evento reproduz a do traço."""
    s, fi = solver
    _, inp = quantize_inputs(3000, 1.15e-3, 0.9, 0.04, 330.0, 25.0, -140, 135, 453.0, True, fi)
    res = s.solve_uncached(inp)
    rpm = inp.rpm

    def tau(p_kpa: float, t_k: float) -> float:  # Douaud-Eyzat, ON 94
        octane_term: float = (94 / 100) ** 3.402
        pressure_term: float = (p_kpa / 101.325) ** -1.7
        return 17.68 * octane_term * pressure_term * math.exp(3800 / t_k) * 1e-3

    dt_deg = 1 / (6 * rpm)
    ev = sum(
        dt_deg / tau(p, t)
        for p, t in zip(res.event_pressure_kpa, res.event_t_unburned_k, strict=True)
    )
    # Recalcula T_u no traço completo IVC→EVO e integra a mesma janela.
    p_ivc = res.pressure_pa[0]
    g = gamma_of_t(inp.t_ivc_k)
    ref = 0.0
    for k, p in enumerate(res.pressure_pa):
        theta = k + inp.ivc_deg
        tu = inp.t_ivc_k * (p / p_ivc) ** ((g - 1) / g)
        g = gamma_of_t(tu)
        if res.event_theta_start <= theta < res.event_theta_start + len(res.event_pressure_kpa):
            ref += dt_deg / tau(p / 1000.0, tu)
    assert ev == pytest.approx(ref, rel=0.005)


def _hold(
    engine: PhysicsEngine, driver: ReferenceDriver, rpm: float, seconds: float, avg_s: float = 0.2
) -> tuple[float, float]:
    dt = engine.resolved.dt
    rig = RpmHoldRig(target_rpm=rpm, inertia_kg_m2=1e4)
    state = None
    n = round(seconds / dt)
    navg = round(avg_s / dt)
    tq = th = 0.0
    for k in range(n):
        sensors = engine.read_sensors()
        state = engine.step(driver.commands(sensors, dt), rig.load(state, engine.rpm, dt), dt)
        if k >= n - navg:
            tq += state.torque_nm
            th += sum(state.theta_pmax_deg_atdc) / engine.n_cyl
    return tq / navg, th / navg


def test_mbt_emerges_between_12_and_18_atdc(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-12: varredura 0–45° a 3000 rpm WOT, λ 0,85: torque máximo com θ_pmax ∈ [12, 18]."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(
        engine, hatch.reference_command_schedule, lambda_target=0.85, advance_deg=0.0
    )
    engine.crank(3000.0)
    _hold(engine, driver, 3000.0, 5.0)
    results = []
    for adv in range(46):
        driver.advance_override = float(adv)
        results.append((adv, *_hold(engine, driver, 3000.0, 0.8)))
    best = max(results, key=lambda r: r[1])
    assert 5 < best[0] < 45  # máximo interior: há um MBT
    assert 12.0 <= best[2] <= 18.0


def test_torque_steady_between_ticks_and_trace_length(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    """RF-03: torque indicado médio varia < 1 % entre ticks a 3000 rpm em regime."""
    engine = make_engine(na_vehicle, noise_enabled=False)
    driver = ReferenceDriver(engine, na_vehicle.reference_command_schedule, throttle_pct=60.0)
    rig = RpmHoldRig(target_rpm=3000.0, inertia_kg_m2=1e4)
    engine.crank(3000.0)
    dt = engine.resolved.dt
    state = None
    torques = []
    for k in range(3000):
        sensors = engine.read_sensors()
        state = engine.step(driver.commands(sensors, dt), rig.load(state, engine.rpm, dt), dt)
        if k > 2500:
            torques.append(state.torque_indicated_nm)
            for ev in state.events:
                assert len(ev.pressure_kpa) == len(ev.t_unburned_k) == len(ev.burned_fraction)
    mean = sum(torques) / len(torques)
    assert max(abs(t / mean - 1) for t in torques) < 0.01
    assert state is not None
    assert len(state.ve_true) == 4


def test_digest_identical_with_and_without_cache(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """D-06/EC-12: o hash não depende da cache (entradas quantizadas sempre)."""
    digests = []
    for size in (0, 8, 4096):
        engine = make_engine(hatch, cycle_cache_size=size, seed=7)
        driver = ReferenceDriver(engine, hatch.reference_command_schedule)
        rig = RpmHoldRig(target_rpm=3500.0)
        engine.crank(3500.0)
        dt = engine.resolved.dt
        state = None
        for _ in range(1500):
            sensors = engine.read_sensors()
            state = engine.step(driver.commands(sensors, dt), rig.load(state, engine.rpm, dt), dt)
        digests.append(engine.state_digest())
        if size == 4096:
            assert engine.solver.hits > 0
    assert len(set(digests)) == 1
