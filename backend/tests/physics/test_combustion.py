"""Wiebe (a = 5, m = 2) e duração de combustão (T096; physics RF-09)."""

from __future__ import annotations

import math

import pytest

from simremap.catalog.contracts import FuelSpec
from simremap.physics.combustion import (
    FlameCoefficients,
    burn_duration_deg,
    flammable,
    ignition_delay_deg,
    laminar_flame_speed,
    reference_flame_speed,
    wiebe_fraction,
    wiebe_rate,
)


def test_wiebe_end_of_combustion() -> None:
    theta0, dur = -15.0, 55.0
    assert wiebe_fraction(theta0, theta0, dur, 5.0, 2.0) == 0.0
    assert wiebe_fraction(theta0 - 10, theta0, dur, 5.0, 2.0) == 0.0
    end = wiebe_fraction(theta0 + dur, theta0, dur, 5.0, 2.0)
    assert end >= 0.993
    assert end == pytest.approx(1 - math.exp(-5.0))
    assert wiebe_fraction(theta0 + 2 * dur, theta0, dur, 5.0, 2.0) == pytest.approx(end)
    # 50 % queimado em y = (ln 2 / 5)^(1/3).
    y50 = (math.log(2) / 5) ** (1 / 3)
    assert wiebe_fraction(theta0 + y50 * dur, theta0, dur, 5.0, 2.0) == pytest.approx(0.5)


def test_wiebe_rate_integrates_to_fraction() -> None:
    theta0, dur = -20.0, 60.0
    n = 6000
    h = dur / n
    total = sum(
        0.5
        * (
            wiebe_rate(theta0 + k * h, theta0, dur, 5, 2)
            + wiebe_rate(theta0 + (k + 1) * h, theta0, dur, 5, 2)
        )
        * h
        for k in range(n)
    )
    assert total == pytest.approx(wiebe_fraction(theta0 + dur, theta0, dur, 5, 2), rel=1e-4)
    assert wiebe_rate(theta0 + dur + 1, theta0, dur, 5, 2) == 0.0


def test_duration_lean_longer_than_rich(fuels: dict[str, FuelSpec]) -> None:
    """RF-09: a λ 1,3 a duração é ≥ 15 % maior que a λ 0,9 no mesmo RPM."""
    co = FlameCoefficients.from_fuel(fuels["e27"])
    lean = burn_duration_deg(3000, 1.3, co, 0.05, 700.0, 2000.0)
    rich = burn_duration_deg(3000, 0.9, co, 0.05, 700.0, 2000.0)
    assert lean >= 1.15 * rich


def test_duration_ethanol_faster_than_gasoline(fuels: dict[str, FuelSpec]) -> None:
    """RF-09: E100 queima ≥ 8 % mais curto que E0 no mesmo ponto."""
    e0 = burn_duration_deg(3000, 1.0, FlameCoefficients.from_fuel(fuels["e0"]), 0.05, 700, 2000)
    e100 = burn_duration_deg(3000, 1.0, FlameCoefficients.from_fuel(fuels["e100"]), 0.05, 700, 2000)
    assert e100 <= 0.92 * e0


def test_duration_scaling_with_rpm_and_residual(fuels: dict[str, FuelSpec]) -> None:
    co = FlameCoefficients.from_fuel(fuels["e0"])
    d3 = burn_duration_deg(3000, 1.0, co, 0.0, 700, 2000)
    d6 = burn_duration_deg(6000, 1.0, co, 0.0, 700, 2000)
    assert d6 / d3 == pytest.approx(2**0.37, rel=1e-9)
    # Referência: E0, φ = 1, sem residual ⇒ Δθ_ref = 55° em qualquer estado (T_u, p).
    assert burn_duration_deg(3000, 1.0, co, 0.0, 600, 900) == pytest.approx(55.0, rel=1e-9)
    assert d3 == pytest.approx(55.0, rel=1e-9)
    with_res = burn_duration_deg(3000, 1.0, co, 0.10, 700, 2000)
    s_ratio = laminar_flame_speed(co, 1.0, 700, 2000, 0.0) / laminar_flame_speed(
        co, 1.0, 700, 2000, 0.10
    )
    assert with_res / d3 == pytest.approx(math.sqrt(s_ratio) * 1.22, rel=1e-9)
    assert reference_flame_speed(700.0, 2000.0) == pytest.approx(
        laminar_flame_speed(FlameCoefficients(0.305, -0.549, 1.21), 1.0, 700.0, 2000.0, 0.0)
    )


def test_ignition_delay_and_flammability() -> None:
    assert ignition_delay_deg(3000) == pytest.approx(4.0)
    assert ignition_delay_deg(12000) == pytest.approx(8.0)
    assert flammable(1.0)
    assert flammable(0.55) and flammable(1.6)
    assert not flammable(0.5)
    assert not flammable(1.7)
