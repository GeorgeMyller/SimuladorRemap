"""PID de RPM e de carga e rampa (T119; dyno RF-07, RF-08)."""

from __future__ import annotations

import pytest
from dyno_helpers import fixture_hatch

from simremap.dyno.contracts import AmbientConditions, DynoRigConfig
from simremap.dyno.controllers import LoadController, Pid, Ramp, RpmController
from simremap.dyno.rig import RPM_TO_RAD_S, Driveline, RollerRig


def test_pid_terms_and_anti_windup_clamping() -> None:
    pid = Pid((2.0, 4.0, 0.0), 0.0, 10.0)
    assert pid.update(1.0, 0.1) == pytest.approx(2.0 + 4.0 * 0.1)
    # Saturado em cima com erro positivo: o integrador congela.
    for _ in range(100):
        assert pid.update(100.0, 0.1) == 10.0
    frozen = pid.integral
    pid.update(100.0, 0.1)
    assert pid.integral == frozen
    # Erro negativo tira da saturação: integra de novo.
    pid.update(-0.1, 0.1)
    assert pid.integral < frozen
    # Saturado em baixo com erro negativo congela; positivo integra.
    low = Pid((1.0, 1.0, 0.0), 0.0, 10.0)
    for _ in range(10):
        assert low.update(-5.0, 0.1) == 0.0
    assert low.integral == 0.0
    pid.reset()
    assert pid.integral == 0.0 and not pid.primed
    with pytest.raises(ValueError, match="out_max"):
        Pid((1.0, 0.0, 0.0), 1.0, 0.0)


def test_pid_derivative_on_error_change() -> None:
    pid = Pid((0.0, 0.0, 0.5), -100.0, 100.0)
    assert pid.update(0.0, 0.01) == 0.0
    assert pid.update(1.0, 0.01) == pytest.approx(0.5 * 1.0 / 0.01)
    assert pid.update(1.0, 0.01, bias=3.0, out_min=-1.0, out_max=4.0) == pytest.approx(3.0)


def test_ramp_reference_and_limit() -> None:
    ramp = Ramp(start_rpm=2000.0, rate_rpm_s=300.0, t0_s=5.0, end_rpm=6300.0)
    assert ramp.at(4.0) == 2000.0
    assert ramp.at(6.0) == pytest.approx(2300.0)
    assert ramp.at(100.0) == 6300.0


def _closed_loop(
    target: float, *, torque_nm: float, ramp: float = 0.0, seconds: float = 6.0
) -> list[float]:
    """Planta 1-GDL do virabrequim acoplada ao rolo com o ``RpmController``."""
    vehicle = fixture_hatch()
    rig_cfg = DynoRigConfig()
    dl = Driveline.from_vehicle(vehicle, rig_cfg)
    rig = RollerRig(rig_cfg, dl, AmbientConditions())
    ctl = RpmController(rig_cfg.rpm_pid, dl, rig_cfg.roller_inertia_kg_m2)
    dt = 1e-3
    rpm = target
    rig.engage(4, rpm)
    j_eng = 0.16
    errors = []
    for k in range(round(seconds / dt)):
        ref = target + ramp * k * dt
        omega = dl.roller_omega(rpm, 4)
        cmd = ctl.command(
            rpm=rpm,
            rpm_ref=ref,
            ref_rate_rpm_s=ramp,
            gear=4,
            brake_torque_nm=torque_nm,
            engine_inertia_kg_m2=j_eng,
            loss_nm=rig.loss_torque(omega),
            capacity_nm=rig.absorber.capacity(omega),
            dt=dt,
        )
        load = rig.load(
            rpm=rpm,
            brake_torque_nm=torque_nm,
            absorber_command_nm=cmd,
            dt=dt,
            pedal_pct=100.0,
            fan_air_speed_m_s=0.0,
        )
        alpha = (torque_nm - load.load_torque_crank_nm) / (j_eng + load.reflected_inertia_kg_m2)
        rpm += alpha / RPM_TO_RAD_S * dt
        errors.append(rpm - ref)
    return errors


def test_rpm_controller_holds_constant_rpm_against_full_torque() -> None:
    errors = _closed_loop(2000.0, torque_nm=350.0)
    tail = errors[-1000:]
    assert max(abs(e) for e in tail) < 25.0


def test_rpm_controller_tracks_ramp_within_50_rpm() -> None:
    errors = _closed_loop(2500.0, torque_nm=350.0, ramp=300.0, seconds=10.0)
    tail = sorted(abs(e) for e in errors[500:])
    assert tail[int(0.95 * len(tail))] <= 50.0


def test_rpm_controller_neutral_returns_zero() -> None:
    vehicle = fixture_hatch()
    cfg = DynoRigConfig()
    ctl = RpmController(cfg.rpm_pid, Driveline.from_vehicle(vehicle, cfg), 300.0)
    assert (
        ctl.command(
            rpm=3000.0,
            rpm_ref=2000.0,
            ref_rate_rpm_s=0.0,
            gear=0,
            brake_torque_nm=100.0,
            engine_inertia_kg_m2=0.16,
            loss_nm=0.0,
            capacity_nm=3000.0,
            dt=1e-3,
        )
        == 0.0
    )
    ctl.reset()


def test_load_controller_fixed_pedal_and_map_pid() -> None:
    ctl = LoadController((0.5, 2.0, 0.0))
    assert ctl.pedal(map_kpa=100.0, map_target_kpa=None, pedal_target_pct=42.0, dt=0.01) == 42.0
    assert ctl.pedal(map_kpa=100.0, map_target_kpa=None, pedal_target_pct=None, dt=0.01) == 0.0
    out = ctl.pedal(map_kpa=100.0, map_target_kpa=150.0, pedal_target_pct=None, dt=0.01)
    assert out == pytest.approx(0.5 * 50.0 + 2.0 * 50.0 * 0.01)
    assert ctl.pedal(map_kpa=400.0, map_target_kpa=150.0, pedal_target_pct=None, dt=0.01) == 0.0
    ctl.reset()
    assert ctl.pid.integral == 0.0
