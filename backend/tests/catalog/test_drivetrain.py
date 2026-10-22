"""RF-18: conversões de potência roda ↔ cambota."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from simremap.catalog.drivetrain import (
    crank_power_kw,
    crank_to_wheel_kw,
    kw_to_whp,
    wheel_to_crank_kw,
    whp_to_kw,
)
from simremap.catalog.loader import Catalog


@dataclass(frozen=True)
class Losses:
    drivetrain_efficiency: float
    drivetrain_fixed_loss_kw: float


def test_hatch_spec_example(real_catalog: Catalog) -> None:
    hatch = real_catalog.vehicles["hatch-20t-gdi"].spec
    assert hatch.drivetrain_efficiency == 0.85
    assert hatch.drivetrain_fixed_loss_kw == 0.0
    assert wheel_to_crank_kw(hatch, 164.1) == pytest.approx(193.1, abs=0.1)
    assert crank_to_wheel_kw(hatch, 193.1) == pytest.approx(164.1, abs=0.1)


@pytest.mark.parametrize("power", [0.0, 50.0, 164.1, 600.0])
def test_round_trip_with_fixed_loss(power: float) -> None:
    losses = Losses(0.88, 4.5)
    assert crank_to_wheel_kw(losses, wheel_to_crank_kw(losses, power)) == pytest.approx(power)
    assert crank_to_wheel_kw(losses, 100.0) == pytest.approx(83.5)
    assert wheel_to_crank_kw(losses, 83.5) == pytest.approx(100.0)


def test_crank_power_and_whp() -> None:
    assert crank_power_kw(307.3, 6000.0) == pytest.approx(193.08, abs=0.01)
    assert kw_to_whp(164.1) == pytest.approx(220.06, abs=0.01)
    assert whp_to_kw(kw_to_whp(123.4)) == pytest.approx(123.4)
