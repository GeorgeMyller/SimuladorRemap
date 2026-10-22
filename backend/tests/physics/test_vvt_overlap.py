"""Cruzamento de válvulas do VVT (002 RF-10; T008, T019).

- Na posição de came de série (``reference_command_schedule``) o efeito é exatamente nulo;
- ``overlap = base + vvt_in − vvt_ex``: escape adiantado (``vvt_ex`` > 0) fecha mais cedo;
- em baixa rotação, overlap maior reduz a VE e aumenta a massa residual;
- em alta rotação com MAP > contrapressão, overlap maior aumenta a VE (lavagem);
- o atuador segue 1.ª ordem com ``VvtSpec.actuator_tau_s`` e limite de 150 °/s.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.physics.contracts import ActuatorCommands
from simremap.physics.engine import VVT_RATE_DEG_S, PhysicsEngine
from simremap.physics.fuel import TrueVolumetricEfficiency, ValveOverlap
from simremap.physics.reference import RpmHoldRig


def _model(vehicle: VehicleSpec) -> tuple[TrueVolumetricEfficiency, ValveOverlap]:
    overlap = ValveOverlap.from_vehicle(vehicle)
    return TrueVolumetricEfficiency(vehicle.engine, overlap), overlap


def _stock_cams(vehicle: VehicleSpec, rpm: float) -> tuple[float, float]:
    point = next(p for p in vehicle.reference_command_schedule.points if p.rpm == rpm)
    return point.vvt_intake_deg, point.vvt_exhaust_deg


def test_stock_position_is_neutral(hatch: VehicleSpec) -> None:
    ve, overlap = _model(hatch)
    plain = TrueVolumetricEfficiency(hatch.engine)
    for point in hatch.reference_command_schedule.points:
        cam_in, cam_ex = point.vvt_intake_deg, point.vvt_exhaust_deg
        assert overlap.delta(point.rpm, cam_in, cam_ex) == 0.0
        assert ve(point.rpm, 200.0, 150.0, cam_in, cam_ex) == plain(point.rpm, 200.0, 150.0, cam_in)
        factor = overlap.residual_factor(0.0, point.rpm, 200.0, 150.0)
        assert factor == 1.0


def test_overlap_base_from_valve_events(hatch: VehicleSpec) -> None:
    overlap = ValveOverlap.from_vehicle(hatch)
    eng = hatch.engine
    assert overlap.base_deg == pytest.approx(0.25 * (eng.ivc_deg_abdc + eng.evo_deg_bbdc))
    assert overlap.overlap_deg(10.0, 5.0) == pytest.approx(overlap.base_deg + 5.0)
    neutral = overlap.overlap_deg(0.0, 0.0)
    assert overlap.overlap_deg(0.0, 5.0) < neutral < overlap.overlap_deg(5.0, 0.0)


def test_exhaust_advance_reduces_overlap_intake_advance_raises(hatch: VehicleSpec) -> None:
    _, overlap = _model(hatch)
    rpm = 2000.0
    cam_in, cam_ex = _stock_cams(hatch, rpm)
    assert overlap.delta(rpm, cam_in, cam_ex + 10.0) < 0.0
    assert overlap.delta(rpm, cam_in + 10.0, cam_ex) > 0.0
    # Avanço igual nos dois cames desloca o cruzamento sem mudar a sua duração.
    assert overlap.delta(rpm, cam_in + 10.0, cam_ex + 10.0) == 0.0


def test_low_rpm_more_overlap_reduces_ve_and_raises_residual(hatch: VehicleSpec) -> None:
    ve, overlap = _model(hatch)
    rpm = 2000.0
    cam_in, cam_ex = _stock_cams(hatch, rpm)
    stock = ve(rpm, 100.0, 105.0, cam_in, cam_ex)
    more = ve(rpm, 100.0, 105.0, cam_in, cam_ex - 15.0)  # escape retardado: fecha mais tarde
    less = ve(rpm, 100.0, 105.0, cam_in, cam_ex + 8.0)  # escape adiantado: fecha mais cedo
    assert more < stock < less
    d_more = overlap.delta(rpm, cam_in, cam_ex - 15.0)
    assert d_more > 0.0
    assert overlap.residual_factor(d_more, rpm, 100.0, 105.0) > 1.0


def test_high_rpm_scavenging_more_overlap_raises_ve(hatch: VehicleSpec) -> None:
    ve, overlap = _model(hatch)
    rpm = 6000.0
    cam_in, cam_ex = _stock_cams(hatch, rpm)
    p_man, p_exh = 220.0, 170.0  # MAP > contrapressão
    stock = ve(rpm, p_man, p_exh, cam_in, cam_ex)
    more = ve(rpm, p_man, p_exh, cam_in, cam_ex - 12.0)  # só o overlap muda (g_vvt é da admissão)
    assert more > stock
    d_more = overlap.delta(rpm, cam_in, cam_ex - 12.0)
    assert overlap.residual_factor(d_more, rpm, p_man, p_exh) < 1.0
    # Com contrapressão acima do coletor o overlap devolve gás queimado: VE cai.
    assert ve(rpm, 150.0, 220.0, cam_in, cam_ex - 12.0) < ve(rpm, 150.0, 220.0, cam_in, cam_ex)


def test_sign_is_bounded() -> None:
    for rpm in (800.0, 2000.0, 3500.0, 5000.0, 8000.0):
        for dp in (-100.0, 0.0, 100.0):
            assert -1.0 <= ValveOverlap.sign(rpm, 150.0 + dp, 150.0) <= 1.0
    assert ValveOverlap.sign(1000.0, 200.0, 100.0) < 0.0
    assert ValveOverlap.sign(7000.0, 200.0, 100.0) > 0.0


def test_vehicle_without_vvt_has_no_overlap_model(
    classic: VehicleSpec, make_engine: Callable[..., PhysicsEngine]
) -> None:
    engine = make_engine(classic, noise_enabled=False)
    assert engine.ve_model.overlap is None


def _hold(engine: PhysicsEngine, intake: float, exhaust: float, ticks: int) -> None:
    dt = engine.resolved.dt
    rig = RpmHoldRig(target_rpm=2000.0)
    n = engine.n_cyl
    cmd = ActuatorCommands(
        t_sim_s=0.0,
        injector_pw_ms=[0.0] * n,
        ignition_advance_deg=[10.0] * n,
        fuel_cut=[True] * n,
        spark_cut=[True] * n,
        throttle_pct=10.0,
        vvt_intake_target_deg=intake,
        vvt_exhaust_target_deg=exhaust,
    )
    state = None
    for _ in range(ticks):
        state = engine.step(cmd, rig.load(state, engine.rpm, dt), dt)


def test_actuator_first_order_with_rate_limit(
    hatch: VehicleSpec, make_engine: Callable[..., PhysicsEngine]
) -> None:
    engine = make_engine(hatch, noise_enabled=False, sim_hz=1000)
    engine.crank(2000.0)
    vvt = hatch.engine.vvt
    assert vvt is not None
    _hold(engine, 40.0, 20.0, 1)
    # Primeiro tick: o passo de 1.ª ordem (40 · (1 − e^(−1 ms/τ))) é limitado a 150 °/s.
    assert engine.vars.vvt_in_deg == pytest.approx(VVT_RATE_DEG_S * 0.001)
    _hold(engine, 40.0, 20.0, 999)
    assert engine.vars.vvt_in_deg == pytest.approx(40.0, abs=0.1)
    assert engine.vars.vvt_ex_deg == pytest.approx(20.0, abs=0.1)
    # Degrau pequeno: só a constante de tempo atua (63 % em τ).
    ticks = round(vvt.actuator_tau_s * 1000)
    _hold(engine, 42.0, 20.0, ticks)
    assert engine.vars.vvt_in_deg - 40.0 == pytest.approx(2.0 * (1 - 1 / 2.718281828), rel=0.02)
