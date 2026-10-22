"""Ar aprisionado, injeção, wall-wetting e lambda (T095; physics RF-05 a RF-08, RF-16)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import FuelSpec, Grid2D, InjectorSpec, VehicleSpec
from simremap.physics.engine import PhysicsEngine
from simremap.physics.errors import PHYSICS_FUEL_CHANGE_WHILE_RUNNING, PhysicsError
from simremap.physics.fuel import (
    InjectorModel,
    TrueVolumetricEfficiency,
    WallFilm,
    collector_lambda,
    evaporative_cooling_k,
    lambda_of,
    residual_fraction,
    trapped_air_kg,
)
from simremap.physics.reference import ReferenceDriver, RpmHoldRig


def injector_550(dead_ms: float = 1.0) -> InjectorSpec:
    grid = Grid2D(
        x_name="battery_v",
        x_values=[10.0, 14.0],
        y_name="dp_kpa",
        y_values=[100.0, 500.0],
        z_values=[[dead_ms, dead_ms], [dead_ms, dead_ms]],
    )
    return InjectorSpec(
        flow_cc_min=550,
        dp_ref_kpa=300,
        rail_pressure_min_kpa=300,
        rail_pressure_max_kpa=300,
        pressure_reference="manifold",
        dead_time_ms=grid,
    )


def test_injected_mass_reference_point(fuels: dict[str, FuelSpec]) -> None:
    """RF-06: 550 cm³/min, Δp 300 kPa, 10,0 ms, dead 1,0 ms, ρ 745 ⇒ 61,5 mg ± 0,5 %."""
    inj = InjectorModel(injector_550(), fuels["e27"])
    mass_mg = inj.mass_kg(10.0, 300.0, 14.0) * 1e6
    assert mass_mg == pytest.approx(61.5, rel=0.005)
    assert inj.mass_kg(1.0, 300.0, 14.0) == 0.0  # pulso ≤ dead time
    assert inj.mass_kg(0.5, 300.0, 14.0) == 0.0
    # √(Δp/Δp_ref) e fator de obstrução.
    assert inj.mass_kg(10.0, 1200.0, 14.0) == pytest.approx(2 * inj.mass_kg(10.0, 300.0, 14.0))
    assert inj.mass_kg(10.0, 300.0, 14.0, 0.5) == pytest.approx(inj.mass_kg(10.0, 300.0, 14.0) / 2)
    # Inverso.
    pulse = inj.pulse_for_mass_ms(61.5e-6, 300.0, 14.0)
    assert inj.mass_kg(pulse, 300.0, 14.0) == pytest.approx(61.5e-6, rel=1e-9)
    assert inj.pulse_for_mass_ms(0.0, 300.0, 14.0) == 0.0


def test_dead_time_interpolation(hatch: VehicleSpec, fuels: dict[str, FuelSpec]) -> None:
    inj = InjectorModel(hatch.injectors, fuels["e27"])
    assert inj.dead_time_ms(14.0, 10_000) == pytest.approx(0.35)
    assert inj.dead_time_ms(13.0, 10_000) == pytest.approx(0.35 * (1.3 + 1.0) / 2)
    assert inj.dead_time_ms(4.0, 10_000) == pytest.approx(0.35 * 2.6)  # borda


def test_lambda_formulas() -> None:
    """RF-08: m_air 500 mg, m_fuel 37,88 mg, E27 ⇒ λ = 1,000 ± 0,002."""
    assert lambda_of(500e-6, 37.88e-6, 13.2) == pytest.approx(1.0, abs=0.002)
    assert lambda_of(500e-6, 0.0, 13.2) is None
    lam_col = collector_lambda([500e-6, 400e-6], [37.88e-6, 37.88e-6], 13.2)
    assert lam_col == pytest.approx(900e-6 / (13.2 * 75.76e-6))
    assert collector_lambda([1.0], [0.0], 13.2) is None


def test_true_ve_residual_and_vvt(hatch: VehicleSpec) -> None:
    ve = TrueVolumetricEfficiency(hatch.engine)
    base = ve.map_value(4000, 100)
    rc = 9.6
    assert ve(4000, 100, 100, 0.0) == pytest.approx(base * (rc - 1.0) / (rc - 1.0))
    assert ve(4000, 100, 200, 0.0) == pytest.approx(base * (rc - 2 ** (1 / 1.4)) / (rc - 1.0))
    assert ve(1000, 100, 100, 50.0) > ve(1000, 100, 100, 0.0)  # avanço ajuda em baixa
    assert ve(7000, 100, 100, 50.0) < ve(7000, 100, 100, 0.0)
    assert 0.2 <= ve(800, 20, 400, 0.0) <= 1.35
    assert trapped_air_kg(1.0, 100.0, 300.0, 5e-4) == pytest.approx(100e3 / (287.05 * 300) * 5e-4)
    m_res, x_r = residual_fraction(100.0, 5e-5, 4e-4, 3e-5)
    assert m_res == pytest.approx(100e3 * 5e-5 / (287.05 * 1000))
    assert x_r == pytest.approx(m_res / (m_res + 4.3e-4))
    assert evaporative_cooling_k(0.0, 1e-3, 512, True) == 0.0
    assert evaporative_cooling_k(1e-4, 1e-3, 512, False) == pytest.approx(
        0.5 * 1e-4 * 512e3 / (1.1e-3 * 1100)
    )


def test_wall_film_model() -> None:
    film = WallFilm(enabled=True, direct_injection=False)
    assert film.parameters(90.0) == pytest.approx((0.25, 0.30))
    x, tau = film.parameters(20.0)
    assert x == pytest.approx(0.95) and tau == pytest.approx(1.2)
    m_cyl, f1 = film.step(0.0, 10e-6, 0.06, 90.0)
    assert m_cyl == pytest.approx(7.5e-6)
    assert f1 == pytest.approx(2.5e-6)
    assert WallFilm(enabled=True, direct_injection=True).parameters(20.0) == (0.02, 0.05)
    assert WallFilm(enabled=False, direct_injection=False).step(1e-6, 5e-6, 0.06, 20.0) == (
        5e-6,
        0.0,
    )


def _steady(
    engine: PhysicsEngine, driver: Any, rpm: float, ticks: int, trace: list[float] | None = None
) -> None:
    rig = RpmHoldRig(target_rpm=rpm, inertia_kg_m2=1e4)
    dt = engine.resolved.dt
    state = None
    for _ in range(ticks):
        sensors = engine.read_sensors()
        state = engine.step(driver.commands(sensors, dt), rig.load(state, engine.rpm, dt), dt)
        if trace is not None:
            trace.append(state.lambda_collector or 0.0)


@pytest.mark.parametrize(("ve_error", "expected"), [(1.0, 1.00), (1.10, 0.91)])
def test_ecu_ve_error_shifts_real_lambda(
    make_engine: Callable[..., PhysicsEngine],
    hatch: VehicleSpec,
    ve_error: float,
    expected: float,
) -> None:
    """RF-05: VE da ECU = física ⇒ λ 1,00 ± 0,01; VE da ECU +10 % ⇒ λ 0,91 ± 0,01."""
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(
        engine,
        hatch.reference_command_schedule,
        throttle_pct=30.0,
        lambda_target=1.0,
        ve_error=ve_error,
    )
    engine.crank(3000.0)
    _steady(engine, driver, 3000.0, 1500)
    state_lam = engine.vars.lambda_col_last
    assert state_lam == pytest.approx(expected, abs=0.01)


def test_wall_wetting_transient_pfi(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    """RF-07: degrau +20 % de pulso a 2000 rpm PFI ⇒ transiente pobre ≥ 3 %, regime em ≤ 1,0 s.

    Ensaiado com o motor quente (ECT 90 °C, X = 0,25, τ = 0,3 s). A 20 °C a fórmula de
    A.3 dá f_T = 4 (X = 1, τ = 1,2 s) e o regresso leva > 1 s (incoerência registada).
    """
    engine = make_engine(na_vehicle, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(
        engine, na_vehicle.reference_command_schedule, throttle_pct=25.0, lambda_target=1.0
    )
    engine.crank(2000.0)
    _steady(engine, driver, 2000.0, 2500)
    lam0 = engine.vars.lambda_col_last
    driver.pulse_scale = 1.2
    trace: list[float] = []
    _steady(engine, driver, 2000.0, 1500, trace)
    final = trace[-1]
    assert final < lam0 * 0.9  # o degrau enriquece
    worst = max(trace[:50])
    assert worst >= final * 1.03  # transiente mais pobre que o regime ≥ 3 %
    settle = next(i for i, lam in enumerate(trace) if abs(lam / final - 1.0) < 0.005)
    assert settle * engine.resolved.dt <= 1.0


def test_wall_wetting_disabled_has_no_transient(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    engine = make_engine(na_vehicle, noise_enabled=False, sim_hz=500, wall_wetting_enabled=False)
    driver = ReferenceDriver(
        engine, na_vehicle.reference_command_schedule, throttle_pct=25.0, lambda_target=1.0
    )
    engine.crank(2000.0)
    _steady(engine, driver, 2000.0, 2500)
    driver.pulse_scale = 1.2
    trace: list[float] = []
    _steady(engine, driver, 2000.0, 1500, trace)
    final = trace[-1]
    # Sem filme, após o primeiro ciclo (≤ 4 eventos) o lambda já está no regime.
    assert all(abs(lam / final - 1.0) < 0.01 for lam in trace[40:])
    assert max(trace[:40]) < final * 1.25


def test_fuel_switch_e27_to_e100_same_pulse(
    make_engine: Callable[..., PhysicsEngine], na_vehicle: VehicleSpec
) -> None:
    """RF-16: mesmo pulso, E27 → E100 ⇒ λ real × (13,2·745)/(9,0·789) = 1,385 ± 1 %."""
    lams = []
    airs = []
    for fuel_id in ("e27", "e100"):
        engine = make_engine(na_vehicle, fuel_id, noise_enabled=False, sim_hz=500)
        driver = ReferenceDriver(engine, na_vehicle.reference_command_schedule, throttle_pct=20.0)
        engine.crank(2500.0)
        _steady(engine, _FixedPulse(driver, engine), 2500.0, 1000)
        lams.append(engine.vars.lambda_col_last)
        airs.append(sum(engine.vars.m_air_last))
    assert airs[1] == pytest.approx(airs[0], rel=2e-3)
    ratio = lams[1] / lams[0]
    assert ratio == pytest.approx((13.2 * 745) / (9.0 * 789), rel=0.01)


class _FixedPulse:
    """Pulso fixo de 3,0 ms com o resto dos comandos do piloto de referência."""

    def __init__(self, driver: ReferenceDriver, engine: PhysicsEngine) -> None:
        self.driver = driver
        self.engine = engine

    def commands(self, sensors: Any, dt: float) -> Any:
        cmd = self.driver.commands(sensors, dt)
        return cmd.model_copy(update={"injector_pw_ms": [3.0] * self.engine.n_cyl})


def test_set_fuel_only_when_stopped(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec, fuels: dict[str, FuelSpec]
) -> None:
    engine = make_engine(hatch)
    engine.set_fuel(fuels["podium"])
    assert engine.fuel.fuel_id == "podium"
    engine.crank(1500.0)
    with pytest.raises(PhysicsError) as exc:
        engine.set_fuel(fuels["e27"])
    assert exc.value.code == PHYSICS_FUEL_CHANGE_WHILE_RUNNING
    assert exc.value.error_status == 409
