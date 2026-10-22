"""PhysicsConfig, passo fixo e geometria (T093; physics RF-01, RF-02; D-07)."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.config import check_dt, resolve_config, substeps
from simremap.physics.contracts import ActuatorCommands, PhysicsConfig, PhysicsFault
from simremap.physics.engine import PhysicsEngine
from simremap.physics.errors import (
    PHYSICS_CONFIG_INVALID,
    PHYSICS_DT_MISMATCH,
    PhysicsError,
)
from simremap.physics.geometry import (
    CrankSchedule,
    CylinderGeometry,
    crank_advance_deg,
    mean_piston_speed,
)
from simremap.physics.reference import free_load


def idle_commands(n: int, *, cut: bool = True) -> ActuatorCommands:
    return ActuatorCommands(
        t_sim_s=0.0,
        injector_pw_ms=[0.0] * n,
        ignition_advance_deg=[10.0] * n,
        fuel_cut=[cut] * n,
        spark_cut=[cut] * n,
        throttle_pct=0.0,
    )


@pytest.mark.parametrize("hz", [99, 1001, 0])
def test_sim_hz_out_of_range_rejected(hz: int) -> None:
    with pytest.raises(ValidationError):
        PhysicsConfig(sim_hz=hz)


@pytest.mark.parametrize("hz", [100, 250, 500, 1000])
def test_dt_is_fixed_inverse_of_sim_hz(hz: int) -> None:
    cfg = PhysicsConfig(sim_hz=hz)
    assert cfg.dt == 1.0 / hz
    check_dt(cfg, 1.0 / hz)
    check_dt(cfg, 1.0 / hz + 5e-13)  # dentro da tolerância de 1e-12 s


def test_dt_mismatch_raises_physics_error() -> None:
    cfg = PhysicsConfig(sim_hz=1000)
    with pytest.raises(PhysicsError) as exc:
        check_dt(cfg, 0.002)
    assert exc.value.code == PHYSICS_DT_MISMATCH
    assert exc.value.error_status == 500
    with pytest.raises(PhysicsError):
        check_dt(cfg, math.nan)


def test_step_with_wrong_dt_rejected_and_state_untouched(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    engine = make_engine(hatch)
    before = engine.state_digest()
    with pytest.raises(PhysicsError) as exc:
        engine.step(idle_commands(4), free_load(), 0.002)
    assert exc.value.code == PHYSICS_DT_MISMATCH
    assert engine.state_digest() == before


def test_substeps_cover_dt() -> None:
    assert substeps(1e-3) == 1
    assert substeps(1e-2) == 10
    assert substeps(1 / 300) == 4


def test_config_wall_wetting_defaults(
    hatch: VehicleSpec, na_vehicle: VehicleSpec, fuels: Any
) -> None:
    assert resolve_config(PhysicsConfig(), hatch, fuels["e27"]).wall_wetting is False  # GDI
    assert resolve_config(PhysicsConfig(), na_vehicle, fuels["e27"]).wall_wetting is True  # PFI
    forced = PhysicsConfig(wall_wetting_enabled=True)
    assert resolve_config(forced, hatch, fuels["e27"]).wall_wetting is True


def test_config_invalid_faults(hatch: VehicleSpec, na_vehicle: VehicleSpec, fuels: Any) -> None:
    bad_cyl = PhysicsConfig(
        faults=[PhysicsFault(kind="injector_clogged", cylinder=6, injector_flow_factor=0.8)]
    )
    with pytest.raises(PhysicsError) as exc:
        PhysicsEngine(bad_cyl, hatch, fuels["e27"])
    assert exc.value.code == PHYSICS_CONFIG_INVALID
    stuck = PhysicsConfig(faults=[PhysicsFault(kind="wastegate_stuck", stuck_position_pct=0.0)])
    with pytest.raises(PhysicsError) as exc2:
        PhysicsEngine(stuck, na_vehicle, fuels["e27"])
    assert exc2.value.code == PHYSICS_CONFIG_INVALID


def test_geometry_volumes(hatch: VehicleSpec) -> None:
    geo = CylinderGeometry.from_engine(hatch.engine)
    vd = math.pi / 4 * 0.0825**2 * 0.0928
    assert geo.vd_cyl_m3 == pytest.approx(vd, rel=1e-12)
    assert geo.vd_total_m3 * 1e6 == pytest.approx(1984.3, abs=0.1)
    assert geo.volume_m3[360] == pytest.approx(geo.vc_m3, rel=1e-12)  # PMS
    assert geo.volume_m3[360 + 180] == pytest.approx(geo.vc_m3 + vd, rel=1e-12)  # PMI
    assert geo.volume_m3[360 + 180] / geo.vc_m3 == pytest.approx(9.6, rel=1e-9)
    assert geo.dvol_m3_per_deg[360] == pytest.approx(0.0, abs=1e-15)
    # dV/dθ tabelado coincide com a derivada numérica de V(θ) analítico.
    for theta in (-120, -45, 30, 90, 150):
        num = (geo.volume_at(theta + 1e-4) - geo.volume_at(theta - 1e-4)) / 2e-4
        assert geo.dvol_m3_per_deg[theta + 360] == pytest.approx(num, rel=1e-6)
        assert geo.dvolume_at(theta) * math.pi / 180 == pytest.approx(num, rel=1e-6)
    assert min(geo.wall_area_m2) > 2 * geo.piston_area_m2


def test_crank_advance_and_piston_speed() -> None:
    assert crank_advance_deg(6000.0, 1e-3) == pytest.approx(36.0)
    assert crank_advance_deg(1000.0, 1e-2) == pytest.approx(60.0)
    assert mean_piston_speed(0.0928, 6000.0) == pytest.approx(18.56)


def test_crank_schedule_phases(hatch: VehicleSpec, muscle: VehicleSpec) -> None:
    sched = CrankSchedule.from_engine(hatch.engine)
    assert sched.tdc_phase_deg == (0.0, 540.0, 180.0, 360.0)  # 1-3-4-2
    assert sched.local_angle(10.0, 0) == pytest.approx(10.0)
    assert sched.local_angle(530.0, 1) == pytest.approx(-10.0)
    v8 = CrankSchedule.from_engine(muscle.engine)
    assert sorted(v8.tdc_phase_deg) == [90.0 * k for k in range(8)]
    assert sched.crossings(0.0, 0.0, -140.0) == []


def test_event_count_and_firing_order_at_6000_rpm(
    make_engine: Callable[..., PhysicsEngine], hatch: VehicleSpec
) -> None:
    """RF-02: 6000 rpm durante 1,0 s num 4 cilindros ⇒ 200 ± 1 eventos na ordem 1-3-4-2."""
    engine = make_engine(hatch, noise_enabled=False)
    engine.crank(6000.0)
    load = free_load(inertia_kg_m2=1e7)  # inércia enorme: rotação constante
    cylinders: list[int] = []
    cmd = idle_commands(4)
    for _ in range(1000):
        state = engine.step(cmd, load, engine.resolved.dt)
        cylinders.extend(ev.cylinder for ev in state.events)
    assert abs(len(cylinders) - 200) <= 1
    assert engine.rpm == pytest.approx(6000.0, rel=1e-3)
    order = [1, 3, 4, 2]
    start = order.index(cylinders[0])
    expected = [order[(start + k) % 4] for k in range(len(cylinders))]
    assert cylinders == expected


def test_event_count_at_low_sim_hz(
    make_engine: Callable[..., PhysicsEngine], muscle: VehicleSpec
) -> None:
    """A 100 Hz e 7500 rpm caem vários eventos por tick, todos por ordem de ângulo."""
    engine = make_engine(muscle, sim_hz=100, noise_enabled=False)
    engine.crank(7500.0)
    load = free_load(inertia_kg_m2=1e7)
    total = 0
    per_tick: list[int] = []
    for _ in range(100):
        state = engine.step(idle_commands(8), load, engine.resolved.dt)
        total += len(state.events)
        per_tick.append(len(state.events))
        times = [ev.t_sim_s for ev in state.events]
        assert times == sorted(times)
    assert abs(total - 7500 / 120 * 8) <= 1
    assert max(per_tick) >= 5
