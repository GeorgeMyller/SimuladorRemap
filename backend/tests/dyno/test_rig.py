"""Rolo, perdas, absorvedor de Foucault e medição (T118; dyno RF-04, RF-05, RF-12)."""

from __future__ import annotations

import math

import pytest
from dyno_helpers import fixture_hatch

from simremap.dyno.contracts import AmbientConditions, DynoRigConfig
from simremap.dyno.rig import (
    HP_KW,
    RPM_TO_RAD_S,
    AccelerationWindow,
    Driveline,
    EddyCurrentAbsorber,
    RollerRig,
    measure_roll,
)

RIG = DynoRigConfig()


@pytest.fixture
def driveline() -> Driveline:
    return Driveline.from_vehicle(fixture_hatch(), RIG)


def test_driveline_ratios_and_reflected_inertia(driveline: Driveline) -> None:
    g = 0.92 * 4.12
    k = 0.316 / 0.6096
    assert driveline.overall_ratio(4) == pytest.approx(g)
    assert driveline.k == pytest.approx(k)
    assert driveline.wheel_to_crank_ratio(4) == pytest.approx(g / k)
    assert driveline.reflected_inertia(4, 300.0) == pytest.approx((300.0 * k**2 + 2.4) / g**2)
    assert driveline.overall_ratio(0) == 0.0
    assert driveline.reflected_inertia(0, 300.0) == 0.0
    assert driveline.wheel_to_crank_ratio(0) == 0.0
    omega = driveline.roller_omega(3000.0, 4)
    assert omega == pytest.approx(3000.0 * RPM_TO_RAD_S * k / g)
    assert driveline.crank_rpm(omega, 4) == pytest.approx(3000.0)
    assert driveline.roller_omega(3000.0, 0) == 0.0
    assert driveline.crank_rpm(10.0, 0) == 0.0
    with pytest.raises(ValueError, match="marcha"):
        driveline.overall_ratio(7)


def test_rf04_free_roll_deceleration_matches_losses(driveline: Driveline) -> None:
    """Motor desacoplado, ω_roll 50 rad/s e absorvedor a 0: α = −T_loss/J (erro < 1 %)."""
    dt = 1e-3
    rig = RollerRig(RIG, driveline, AmbientConditions())
    rig.omega_roll = 50.0
    expected = -(RIG.loss_c0_nm + RIG.loss_c1_nm_s_rad * 50.0) / RIG.roller_inertia_kg_m2
    omegas = [rig.omega_roll]
    for _ in range(200):
        load = rig.load(
            rpm=0.0,
            brake_torque_nm=0.0,
            absorber_command_nm=0.0,
            dt=dt,
            pedal_pct=0.0,
            fan_air_speed_m_s=0.0,
        )
        assert load.load_torque_crank_nm == 0.0
        assert load.reflected_inertia_kg_m2 == 0.0
        omegas.append(rig.omega_roll)
    window = AccelerationWindow[None](21, dt)
    alphas = [out[0] for w in omegas if (out := window.push(w, None)) is not None]
    measured = alphas[0]
    assert measured == pytest.approx(expected, rel=0.01)
    assert rig.loss_torque(0.0) == 0.0


def test_absorber_first_order_capacity_and_power_limit() -> None:
    absorber = EddyCurrentAbsorber(RIG)
    omega = 30.0
    cap = absorber.capacity(omega)
    assert cap == pytest.approx(min(3000.0 * (1 - math.exp(-3.0)), 600_000.0 / omega))
    dt = 1e-3
    for _ in range(50):  # 1 τ
        absorber.step(1000.0, omega, dt)
    assert absorber.torque_nm == pytest.approx(1000.0 * (1 - math.exp(-1.0)), rel=1e-6)
    for _ in range(2000):
        absorber.step(10_000.0, omega, dt)
    assert absorber.torque_nm == pytest.approx(cap)
    assert absorber.step(-500.0, omega, dt) >= 0.0  # o absorvedor não motoriza
    assert absorber.capacity(0.0) == 0.0
    assert absorber.capacity(1000.0) == pytest.approx(600.0)  # 600 kW / 1000 rad/s
    absorber.reset()
    assert absorber.torque_nm == 0.0


def test_coupled_load_reflects_absorber_losses_and_drivetrain(driveline: Driveline) -> None:
    rig = RollerRig(RIG, driveline, AmbientConditions())
    rig.engage(4, 3000.0)
    assert rig.coupled
    omega = driveline.roller_omega(3000.0, 4)
    assert rig.omega_roll == pytest.approx(omega)
    load = rig.load(
        rpm=3000.0,
        brake_torque_nm=300.0,
        absorber_command_nm=0.0,
        dt=1e-3,
        pedal_pct=150.0,
        fan_air_speed_m_s=12.0,
    )
    g, k = driveline.overall_ratio(4), driveline.k
    t_loss = RIG.loss_c0_nm + RIG.loss_c1_nm_s_rad * omega
    assert load.load_torque_crank_nm == pytest.approx(t_loss * k / g + 0.15 * 300.0)
    assert load.reflected_inertia_kg_m2 == pytest.approx(driveline.reflected_inertia(4, 300.0))
    assert load.wheel_to_crank_ratio == pytest.approx(g / k)
    assert load.gear == 4
    assert load.pedal_pct == 100.0
    assert load.vehicle_speed_kmh == pytest.approx(omega * 0.6096 * 3.6)
    assert rig.after_step(3100.0) == pytest.approx(driveline.roller_omega(3100.0, 4))
    with pytest.raises(ValueError, match="marcha"):
        rig.engage(9, 1000.0)


def test_fixed_driveline_loss_is_added_at_the_crank() -> None:
    vehicle = fixture_hatch().model_copy(update={"drivetrain_fixed_loss_kw": 5.0})
    dl = Driveline.from_vehicle(vehicle, RIG)
    rig = RollerRig(RIG, dl, AmbientConditions())
    rig.engage(4, 3000.0)
    load = rig.load(
        rpm=3000.0,
        brake_torque_nm=0.0,
        absorber_command_nm=0.0,
        dt=1e-3,
        pedal_pct=0.0,
        fan_air_speed_m_s=0.0,
    )
    omega = dl.roller_omega(3000.0, 4)
    t_loss = RIG.loss_c0_nm + RIG.loss_c1_nm_s_rad * omega
    expected = t_loss * dl.k / dl.overall_ratio(4) + 5000.0 / (3000.0 * RPM_TO_RAD_S)
    assert load.load_torque_crank_nm == pytest.approx(expected)


def test_rf05_power_from_synthetic_constant_acceleration(driveline: Driveline) -> None:
    """α = 20 rad/s² e T_abs conhecido: P_roll com erro < 0,5 % face ao analítico."""
    dt = 1e-3
    window = AccelerationWindow[float](21, dt)
    t_abs, omega0 = 450.0, 20.0
    result = None
    for i in range(21):
        result = window.push(omega0 + 20.0 * i * dt, omega0 + 20.0 * i * dt)
    assert result is not None
    alpha, omega_centre = result
    t_loss = RIG.loss_c0_nm + RIG.loss_c1_nm_s_rad * omega_centre
    m = measure_roll(
        roller_inertia_kg_m2=300.0,
        omega_roll=omega_centre,
        alpha_roll=alpha,
        absorber_nm=t_abs,
        loss_nm=t_loss,
        overall_ratio=driveline.overall_ratio(4),
        k=driveline.k,
        efficiency=0.85,
    )
    analytic = (300.0 * 20.0 + t_abs + t_loss) * (omega0 + 20.0 * 10 * dt)
    assert m.power_wheel_w == pytest.approx(analytic, rel=0.005)
    assert m.alpha_roll == pytest.approx(20.0)
    wheel_omega = omega_centre / driveline.k
    assert m.torque_wheel_nm == pytest.approx(m.power_wheel_w / wheel_omega)
    assert m.torque_engine_nm == pytest.approx(
        m.torque_wheel_nm / (driveline.overall_ratio(4) * 0.85)
    )
    assert m.whp == pytest.approx(m.power_wheel_kw / HP_KW)


def test_rf12_crank_power_from_wheel_power() -> None:
    """η_drv 0,85 e P_wheel 164,1 kW ⇒ P_crank 193,1 kW ± 0,1."""
    omega = 100.0
    torque_roll = 164_100.0 / omega
    m = measure_roll(
        roller_inertia_kg_m2=300.0,
        omega_roll=omega,
        alpha_roll=0.0,
        absorber_nm=torque_roll,
        loss_nm=0.0,
        overall_ratio=3.79,
        k=0.518,
        efficiency=0.85,
    )
    assert m.power_wheel_kw == pytest.approx(164.1)
    assert m.power_crank_w / 1000.0 == pytest.approx(193.1, abs=0.1)


def test_measure_roll_degenerate_cases() -> None:
    m = measure_roll(
        roller_inertia_kg_m2=300.0,
        omega_roll=0.0,
        alpha_roll=0.0,
        absorber_nm=0.0,
        loss_nm=0.0,
        overall_ratio=0.0,
        k=0.0,
        efficiency=0.85,
    )
    assert m.torque_wheel_nm == 0.0
    assert m.torque_engine_nm == 0.0


def test_acceleration_window_validation_and_reset() -> None:
    with pytest.raises(ValueError, match="ímpar"):
        AccelerationWindow[int](4, 1e-3)
    window = AccelerationWindow[int](5, 1e-3)
    assert window.push(1.0, 1) is None
    readiness = [window.ready]
    for i in range(4):
        window.push(1.0 + i, i)
    readiness.append(window.ready)
    window.reset()
    readiness.append(window.ready)
    assert readiness == [False, True, False]
