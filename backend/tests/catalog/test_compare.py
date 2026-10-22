"""RF-22 / D-30: ``compare_to_reference`` com séries sintéticas."""

from __future__ import annotations

import struct

import pytest

from simremap.catalog.compare import compare_to_reference, reference_correction
from simremap.catalog.contracts import Quantity, ReferenceCurve, ReferenceCurvePoint
from simremap.catalog.loader import Catalog


def _scaled(curve: ReferenceCurve, factor: float) -> list[ReferenceCurvePoint]:
    return [
        ReferenceCurvePoint(
            rpm=p.rpm,
            torque_crank_nm=None if p.torque_crank_nm is None else p.torque_crank_nm * factor,
            power_wheel_kw=None if p.power_wheel_kw is None else p.power_wheel_kw * factor,
            lambda_value=None if p.lambda_value is None else p.lambda_value * factor,
            egt_c=None if p.egt_c is None else p.egt_c * factor,
        )
        for p in curve.points
    ]


@pytest.fixture
def hatch_curve(real_catalog: Catalog) -> ReferenceCurve:
    return real_catalog.vehicles["hatch-20t-gdi"].curves[0]


def test_identity_is_zero(hatch_curve: ReferenceCurve) -> None:
    result = compare_to_reference(hatch_curve, list(hatch_curve.points))
    assert result.passed
    assert result.not_compared == []
    assert [d.quantity for d in result.deviations] == list(hatch_curve.quantities)
    assert all(d.max_deviation_pct == 0.0 and d.points_compared == 19 for d in result.deviations)


def test_four_percent_passes(hatch_curve: ReferenceCurve) -> None:
    result = compare_to_reference(hatch_curve, _scaled(hatch_curve, 1.04))
    assert result.passed
    for dev in result.deviations:
        assert dev.max_deviation_pct == pytest.approx(4.0, abs=1e-9)


def test_six_percent_fails(hatch_curve: ReferenceCurve) -> None:
    result = compare_to_reference(hatch_curve, _scaled(hatch_curve, 1.06))
    assert not result.passed
    assert max(d.max_deviation_pct for d in result.deviations) == pytest.approx(6.0, abs=1e-9)


def test_egt_compared_in_celsius(hatch_curve: ReferenceCurve) -> None:
    sim = [p.model_copy(update={"egt_c": (p.egt_c or 0.0) + 46.0}) for p in hatch_curve.points]
    result = compare_to_reference(hatch_curve, sim)
    egt = next(d for d in result.deviations if d.quantity == "egt_c")
    # pior ponto: a menor EGT (720 °C a 2000 rpm) → 46/720 = 6,39 % (em K seria 4,7 %)
    assert egt.max_deviation_pct == pytest.approx(46.0 / 720.0 * 100.0)
    assert egt.rpm_at_max == 2000.0
    assert not result.passed


def test_linear_interpolation_between_simulated_points(hatch_curve: ReferenceCurve) -> None:
    # Série simulada só nas âncoras de 500 rpm: os pontos de 250 rpm da referência são a
    # interpolação linear das âncoras (arredondada a 0,1 N·m) → desvio só de arredondamento.
    sim = [p for p in hatch_curve.points if p.rpm % 500 == 0]
    result = compare_to_reference(hatch_curve, sim)
    torque = next(d for d in result.deviations if d.quantity == "torque_crank_nm")
    assert torque.points_compared == 19
    assert torque.max_deviation_pct < 0.02


def test_interpolated_value_is_used(hatch_curve: ReferenceCurve) -> None:
    # Simulação com 2 pontos: torque 300 a 2000 rpm e 400 a 6500 rpm (reta). A 4250 rpm a
    # simulação vale 350 = referência; o pior ponto é 6500 rpm (|400 − 276| / 276).
    sim = [
        ReferenceCurvePoint(rpm=2000.0, torque_crank_nm=300.0),
        ReferenceCurvePoint(rpm=6500.0, torque_crank_nm=400.0),
    ]
    result = compare_to_reference(hatch_curve, sim)
    torque = result.deviations[0]
    assert torque.quantity == "torque_crank_nm"
    assert torque.points_compared == 19
    assert torque.rpm_at_max == 6500.0
    assert torque.max_deviation_pct == pytest.approx((400.0 - 276.0) / 276.0 * 100.0)
    assert result.not_compared == ["power_wheel_kw", "lambda_value", "egt_c"]


def test_points_outside_simulated_range_do_not_count(hatch_curve: ReferenceCurve) -> None:
    sim = [p for p in hatch_curve.points if 3000 <= p.rpm <= 4000]
    result = compare_to_reference(hatch_curve, sim)
    assert all(d.points_compared == 5 for d in result.deviations)
    assert not result.passed  # menos de 8 pontos comparados


def test_quantity_missing_in_simulation(hatch_curve: ReferenceCurve) -> None:
    sim = [p.model_copy(update={"lambda_value": None}) for p in hatch_curve.points]
    result = compare_to_reference(hatch_curve, sim)
    assert result.not_compared == ["lambda_value"]
    assert "lambda_value" not in [d.quantity for d in result.deviations]
    assert not result.passed


def test_curve_without_lambda_and_egt(hatch_curve: ReferenceCurve) -> None:
    quantities: list[Quantity] = ["torque_crank_nm", "power_wheel_kw"]
    curve = hatch_curve.model_copy(
        update={
            "quantities": quantities,
            "points": [p.model_copy(update={"lambda_value": None, "egt_c": None})
                       for p in hatch_curve.points],
        }
    )  # fmt: skip
    result = compare_to_reference(curve, _scaled(hatch_curve, 1.02))
    assert result.passed
    assert result.not_compared == ["lambda_value", "egt_c"]


def test_tolerance_from_curve(hatch_curve: ReferenceCurve) -> None:
    strict = hatch_curve.model_copy(update={"tolerance_pct": 3.0})
    assert not compare_to_reference(strict, _scaled(hatch_curve, 1.04)).passed


def test_bitwise_deterministic(hatch_curve: ReferenceCurve) -> None:
    sim = _scaled(hatch_curve, 1.0337)
    first = compare_to_reference(hatch_curve, sim)
    second = compare_to_reference(hatch_curve, list(sim))
    pack = [struct.pack("<d", d.max_deviation_pct) for d in first.deviations]
    assert pack == [struct.pack("<d", d.max_deviation_pct) for d in second.deviations]
    assert first == second


def test_rejects_unsorted_series(hatch_curve: ReferenceCurve) -> None:
    with pytest.raises(ValueError, match="crescente"):
        compare_to_reference(hatch_curve, list(reversed(hatch_curve.points)))


def test_correction_mapping(hatch_curve: ReferenceCurve) -> None:
    assert reference_correction("none") == "uncorrected"
    assert reference_correction("sae_j1349") == "sae_j1349"
    compare_to_reference(hatch_curve, list(hatch_curve.points), simulated_correction="sae_j1349")
    with pytest.raises(ValueError, match="REFERENCE_CORRECTION_MISMATCH"):
        compare_to_reference(hatch_curve, list(hatch_curve.points), simulated_correction="none")
    uncorrected = hatch_curve.model_copy(
        update={
            "conditions": hatch_curve.conditions.model_copy(update={"correction": "uncorrected"})
        }
    )
    assert compare_to_reference(
        uncorrected, list(hatch_curve.points), simulated_correction="none"
    ).passed
