"""Acurácia física do catálogo contra o ``Reference Benchmark Baseline v1`` (T117, T217).

- ``test_validated_vehicle_within_tolerance`` (marcador ``accuracy``): varredura headless
  de 2000 rpm à rotação máxima da curva, passo 250 rpm, desvio < 5 % em torque, potência na
  roda, lambda e EGT (°C) para cada veículo ``validated`` (RF-22, RF-29; D-30).
- ``test_all_four_validated_and_bitwise_repeatable`` (``accuracy``): os 4 veículos estão
  ``validated`` e a mesma varredura repetida dá ``max_deviation_pct`` idêntico bit a bit;
  a mesma série comparada 2 vezes também (RF-29).
- Os restantes testes (rápidos) cobrem o contrato de ``simremap.catalog.accuracy``.
"""

from __future__ import annotations

import itertools
import math

import pytest

from simremap.catalog.accuracy import (
    SWEEP_START_RPM,
    AccuracyResult,
    SweepPoint,
    reference_sweep,
    run_accuracy,
    sweep_rpms,
)
from simremap.catalog.compare import compare_to_reference
from simremap.catalog.loader import Catalog

VEHICLES = ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]
# PRD seção 7: potência de série (whp) com tolerância do benchmark.
PRD_PEAK_WHP = {"hatch-20t-gdi": 220.0, "coupe-30t-i6": 340.0, "muscle-v8-sc": 460.0}

_RESULTS: dict[str, AccuracyResult] = {}


def _result(catalog: Catalog, vehicle_id: str) -> AccuracyResult:
    if vehicle_id not in _RESULTS:
        _RESULTS[vehicle_id] = run_accuracy(catalog, vehicle_id)
    return _RESULTS[vehicle_id]


@pytest.mark.accuracy
@pytest.mark.parametrize("vehicle_id", VEHICLES)
def test_validated_vehicle_within_tolerance(real_catalog: Catalog, vehicle_id: str) -> None:
    entry = real_catalog.vehicles[vehicle_id]
    if entry.spec.validation_status != "validated":
        pytest.skip("veículo em draft")
    result = _result(real_catalog, vehicle_id)
    curve = entry.curves[0]
    assert [p.rpm for p in result.points] == sweep_rpms(curve)
    assert result.points[0].rpm == max(SWEEP_START_RPM, curve.points[0].rpm)
    assert result.points[-1].rpm == curve.points[-1].rpm
    detail = {
        d.quantity: (round(d.max_deviation_pct, 2), d.rpm_at_max)
        for d in result.comparison.deviations
    }
    assert result.comparison.passed, detail
    assert {d.quantity for d in result.comparison.deviations} == set(curve.quantities)
    assert all(d.max_deviation_pct < curve.tolerance_pct for d in result.comparison.deviations)
    lim = entry.spec.mechanical_limits
    for point in result.points:  # série dentro dos limites mecânicos (sem dano de série)
        assert point.p_max_bar < lim.max_cylinder_pressure_bar
        assert point.piston_temp_c < lim.max_piston_temp_c
        assert point.egt_c < lim.egt_max_c
        if point.turbo_rpm is not None and lim.turbo_max_rpm is not None:
            assert point.turbo_rpm < lim.turbo_max_rpm
    if vehicle_id in PRD_PEAK_WHP:
        assert result.peak_whp == pytest.approx(PRD_PEAK_WHP[vehicle_id], rel=0.05)
    else:  # clássico: faixa 300-600 whp com E100 (PRD seção 7, item 3)
        assert 300.0 * 0.95 <= result.peak_whp <= 600.0


@pytest.mark.accuracy
def test_all_four_validated_and_bitwise_repeatable(real_catalog: Catalog) -> None:
    assert [
        v for v in VEHICLES if real_catalog.vehicles[v].spec.validation_status == "validated"
    ] == VEHICLES
    for vehicle_id in VEHICLES:
        first = _result(real_catalog, vehicle_id)
        again = run_accuracy(real_catalog, vehicle_id)
        assert again.points == first.points
        a = [d.max_deviation_pct for d in first.comparison.deviations]
        b = [d.max_deviation_pct for d in again.comparison.deviations]
        assert [x.hex() for x in a] == [y.hex() for y in b]
        curve = real_catalog.vehicles[vehicle_id].curves[0]
        series = [p.as_curve_point() for p in first.points]
        c1 = compare_to_reference(curve, series)
        c2 = compare_to_reference(curve, series)
        assert [d.max_deviation_pct.hex() for d in c1.deviations] == [
            d.max_deviation_pct.hex() for d in c2.deviations
        ]


# --------------------------------------------------------------------------- contrato rápido


def test_short_sweep_contract(real_catalog: Catalog) -> None:
    entry = real_catalog.vehicles["hatch-20t-gdi"]
    fuel = real_catalog.fuels["e27"]
    points = reference_sweep(entry.spec, fuel, [3000.0, 3250.0], first_point_s=0.4, point_s=0.4)
    assert [p.rpm for p in points] == [3000.0, 3250.0]
    for p in points:
        assert isinstance(p, SweepPoint)
        assert all(math.isfinite(v) for v in (p.torque_crank_nm, p.egt_c, p.map_kpa))
        assert p.turbo_rpm is not None
        cp = p.as_curve_point()
        assert 0.6 <= (cp.lambda_value or 0.0) <= 1.3
        assert 200.0 <= (cp.egt_c or 0.0) <= 1100.0
        assert (cp.torque_crank_nm or 0.0) >= 0.0


def test_supercharged_sweep_has_no_turbo(real_catalog: Catalog) -> None:
    entry = real_catalog.vehicles["muscle-v8-sc"]
    points = reference_sweep(entry.spec, real_catalog.fuels["e27"], [2500.0], first_point_s=0.2)
    assert points[0].turbo_rpm is None


@pytest.mark.parametrize("rpms", [[], [3000.0, 3000.0], [3500.0, 3000.0]])
def test_sweep_rejects_bad_rpms(real_catalog: Catalog, rpms: list[float]) -> None:
    entry = real_catalog.vehicles["hatch-20t-gdi"]
    with pytest.raises(ValueError, match="estritamente crescente"):
        reference_sweep(entry.spec, real_catalog.fuels["e27"], rpms)


def test_sweep_rejects_zero_duration(real_catalog: Catalog) -> None:
    entry = real_catalog.vehicles["hatch-20t-gdi"]
    with pytest.raises(ValueError, match="menor que um passo"):
        reference_sweep(entry.spec, real_catalog.fuels["e27"], [3000.0], first_point_s=0.0)


def test_sweep_rpms_and_unknown_vehicle(real_catalog: Catalog) -> None:
    curve = real_catalog.vehicles["coupe-30t-i6"].curves[0]
    rpms = sweep_rpms(curve)
    assert rpms[0] == 2000.0  # a curva do coupé começa em 1500 rpm
    assert all(b - a == 250.0 for a, b in itertools.pairwise(rpms))
    assert sweep_rpms(real_catalog.vehicles["classic-20t-swap"].curves[0])[0] == 3000.0
    with pytest.raises(KeyError):
        run_accuracy(real_catalog, "nao-existe-00")
