"""Correção SAE J1349 e DIN 70020 com fator constante por puxada (T120; dyno RF-10; D-29)."""

from __future__ import annotations

import math

import pytest

from simremap.dyno.contracts import AmbientConditions, CorrectionStandard
from simremap.dyno.correction import (
    CF_MAX,
    CF_MIN,
    correction_factor,
    dry_pressure_kpa,
    raw_correction_factor,
    vapor_pressure_kpa,
)

SAE = CorrectionStandard.SAE_J1349
DIN = CorrectionStandard.DIN_70020


def test_sae_reference_conditions_give_unity() -> None:
    result = correction_factor(SAE, AmbientConditions(temperature_c=25.0, pressure_kpa=99.0))
    assert result.factor == pytest.approx(1.0, abs=0.001)
    assert not result.out_of_range
    assert result.standard == SAE


def test_din_reference_conditions_give_unity() -> None:
    result = correction_factor(DIN, AmbientConditions(temperature_c=20.0, pressure_kpa=101.3))
    assert result.factor == pytest.approx(1.0, abs=0.001)


def test_none_standard_is_unity() -> None:
    hot = AmbientConditions(temperature_c=45.0, pressure_kpa=70.0)
    assert correction_factor(CorrectionStandard.NONE, hot).factor == 1.0


def test_magnus_vapor_pressure_and_dry_air() -> None:
    p_sat_20 = 0.61094 * math.exp(17.625 * 20.0 / (20.0 + 243.04))
    assert vapor_pressure_kpa(20.0, 0.5) == pytest.approx(0.5 * p_sat_20)
    amb = AmbientConditions(temperature_c=20.0, pressure_kpa=100.0, relative_humidity=0.5)
    assert dry_pressure_kpa(amb) == pytest.approx(100.0 - 0.5 * p_sat_20)


def test_sae_formula_with_humidity_and_heat() -> None:
    amb = AmbientConditions(temperature_c=35.0, pressure_kpa=97.0, relative_humidity=0.6)
    p_d = dry_pressure_kpa(amb)
    expected = 1.18 * (99.0 / p_d) * math.sqrt((35.0 + 273.15) / 298.15) - 0.18
    assert raw_correction_factor(SAE, amb) == pytest.approx(expected)
    assert correction_factor(SAE, amb).factor == pytest.approx(expected)
    assert expected > 1.0


def test_din_formula() -> None:
    amb = AmbientConditions(temperature_c=30.0, pressure_kpa=95.0)
    expected = (101.325 / 95.0) * math.sqrt(303.15 / 293.15)
    assert raw_correction_factor(DIN, amb) == pytest.approx(expected)


def test_ec08_extreme_ambient_is_clamped_and_flagged() -> None:
    extreme = AmbientConditions(temperature_c=45.0, pressure_kpa=70.0)
    result = correction_factor(SAE, extreme)
    assert result.raw_factor > CF_MAX
    assert result.factor == CF_MAX
    assert result.out_of_range
    cold = AmbientConditions(temperature_c=-20.0, pressure_kpa=110.0)
    low = correction_factor(DIN, cold)
    assert low.raw_factor < CF_MIN or low.factor >= CF_MIN
    assert CF_MIN <= low.factor <= CF_MAX
