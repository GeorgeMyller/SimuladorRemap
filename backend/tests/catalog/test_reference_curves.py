"""RF-12, RF-13, RF-29: curvas do ``Reference Benchmark Baseline v1``."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from simremap.catalog.canonical import benchmark_sha256, canonical_sha256
from simremap.catalog.contracts import BENCHMARK_ID, KW_PER_HP
from simremap.catalog.drivetrain import crank_power_kw, crank_to_wheel_kw
from simremap.catalog.loader import Catalog

# Âncoras do Apêndice A.4 (rpm, torque N·m, potência na roda kW, lambda, EGT °C).
ANCHORS: dict[str, list[tuple[float, float, float, float, float]]] = {
    "hatch-20t-gdi": [
        (2000, 350.0, 62.3, 0.95, 720), (3000, 350.0, 93.5, 0.95, 800),
        (4000, 350.0, 124.6, 0.90, 870), (5000, 345.0, 153.5, 0.85, 905),
        (5500, 331.0, 162.0, 0.83, 915), (6000, 307.3, 164.1, 0.82, 920),
        (6500, 276.0, 159.7, 0.82, 925),
    ],
    "coupe-30t-i6": [
        (1500, 430.0, 57.4, 0.98, 700), (2000, 500.0, 89.0, 0.95, 760),
        (5000, 500.0, 222.5, 0.82, 910), (6000, 474.5, 253.4, 0.80, 940),
        (7000, 380.0, 236.8, 0.80, 950),
    ],
    "classic-20t-swap": [
        (3000, 330.0, 91.2, 0.82, 680), (4000, 430.0, 158.5, 0.80, 740),
        (5000, 450.0, 207.3, 0.78, 790), (6500, 397.0, 237.8, 0.78, 835),
        (7500, 320.0, 221.2, 0.78, 850),
    ],
    "muscle-v8-sc": [
        (2000, 470.0, 83.7, 0.90, 650), (4500, 650.0, 260.4, 0.80, 810),
        (6000, 612.0, 326.9, 0.79, 860), (6500, 593.6, 343.4, 0.79, 870),
        (7500, 490.0, 327.1, 0.79, 880),
    ],
}  # fmt: skip
POINT_COUNTS = {"hatch-20t-gdi": 19, "coupe-30t-i6": 23, "classic-20t-swap": 19, "muscle-v8-sc": 23}


@pytest.mark.parametrize("vehicle_id", list(ANCHORS))
def test_step_and_coverage(real_catalog: Catalog, vehicle_id: str) -> None:
    entry = real_catalog.vehicles[vehicle_id]
    (curve,) = entry.curves
    rpms = [p.rpm for p in curve.points]
    assert all(b - a == 250.0 for a, b in itertools.pairwise(rpms))
    assert rpms[0] <= 3000.0
    assert curve.covers_rev_limit(entry.spec.mechanical_limits.rev_limit_rpm)
    assert len(rpms) == POINT_COUNTS[vehicle_id]
    assert curve.curve_id == f"stock-{entry.spec.stock_fuel_id}"
    assert curve.calibration_ref == "stock"
    assert curve.confidence == "estimated"
    assert curve.license == "internal-estimate"
    assert curve.tolerance_pct == 5.0
    assert curve.benchmark_id == BENCHMARK_ID
    assert curve.quantities == ["torque_crank_nm", "power_wheel_kw", "lambda_value", "egt_c"]


@pytest.mark.parametrize("vehicle_id", list(ANCHORS))
def test_anchor_values(real_catalog: Catalog, vehicle_id: str) -> None:
    (curve,) = real_catalog.vehicles[vehicle_id].curves
    by_rpm = {p.rpm: p for p in curve.points}
    for rpm, torque, p_wheel, lam, egt in ANCHORS[vehicle_id]:
        point = by_rpm[rpm]
        assert point.torque_crank_nm == torque
        assert point.power_wheel_kw == pytest.approx(p_wheel, abs=0.06)
        assert point.lambda_value == pytest.approx(lam, abs=1e-9)
        assert point.egt_c == egt


@pytest.mark.parametrize("vehicle_id", list(ANCHORS))
def test_torque_power_coherence(real_catalog: Catalog, vehicle_id: str) -> None:
    entry = real_catalog.vehicles[vehicle_id]
    for point in entry.curves[0].points:
        assert point.torque_crank_nm is not None and point.power_wheel_kw is not None
        expected = crank_to_wheel_kw(entry.spec, crank_power_kw(point.torque_crank_nm, point.rpm))
        assert abs(point.power_wheel_kw - expected) <= 0.01 * expected


def test_hatch_intermediate_point_interpolated(real_catalog: Catalog) -> None:
    (curve,) = real_catalog.vehicles["hatch-20t-gdi"].curves
    point = next(p for p in curve.points if p.rpm == 2250)
    assert point.torque_crank_nm == 350.0
    assert point.power_wheel_kw == pytest.approx(70.1, abs=0.05)
    assert point.egt_c == 740.0
    assert point.power_wheel_kw is not None
    assert point.power_wheel_whp == pytest.approx(point.power_wheel_kw / KW_PER_HP)


def test_rated_whp_matches_curve_peak(real_catalog: Catalog) -> None:
    for entry in real_catalog.vehicles.values():
        peak = max(p.power_wheel_kw or 0.0 for p in entry.curves[0].points) / KW_PER_HP
        assert abs(entry.spec.rated.peak_power_whp - peak) <= 0.01 * peak


def test_benchmark_sha256(real_catalog: Catalog) -> None:
    entries = [f.model_dump() for f in real_catalog.manifest.files]
    curves = sorted(
        (
            {"path": e["path"], "sha256": e["sha256"]}
            for e in entries
            if "/reference-curves/" in e["path"]
        ),
        key=lambda e: e["path"],
    )
    assert len(curves) == 4
    assert real_catalog.benchmark_sha256 == canonical_sha256(curves) == benchmark_sha256(entries)


def test_benchmark_ignores_other_files() -> None:
    a = [{"path": "vehicles/x-y/reference-curves/c.json", "sha256": "a" * 64}]
    b = [*a, {"path": "fuels/e0.json", "sha256": "b" * 64},
         {"path": "vehicles/x-y/reference-curves/sub/c.json", "sha256": "c" * 64}]  # fmt: skip
    assert benchmark_sha256(a) == benchmark_sha256(b)
    assert benchmark_sha256(reversed(b)) == benchmark_sha256(b)


def test_curve_change_requires_new_version(catalog_copy: Any) -> None:
    from simremap.catalog.errors import CatalogInvalid
    from simremap.catalog.tools.rehash import RehashError, rehash

    copy = catalog_copy
    rel = "vehicles/hatch-20t-gdi/reference-curves/stock-e27.json"
    data = copy.read(rel)
    data["points"][0]["egt_c"] = 721.0
    copy.write(rel, data)
    with pytest.raises(CatalogInvalid):
        copy.load()
    with pytest.raises(RehashError):
        rehash(copy.root)
    rehash(copy.root, "1.2.0")
    reloaded = copy.load()
    assert reloaded.catalog_version == "1.2.0"
