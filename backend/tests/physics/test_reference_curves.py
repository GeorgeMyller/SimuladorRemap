"""Acurácia face ao Reference Benchmark Baseline v1 (physics RNF-02, G-01).

- ``test_hatch_fixture_full_load_sweep``: varredura a plena carga do ``hatch-20t-gdi`` da
  fixture (calibração documentada em ``conftest.py``) contra a tabela A.4 do
  ``vehicle-catalog`` (curva ``stock-e27``): desvio < 5 % em torque, potência na roda,
  lambda e EGT (°C) por ponto; pico ≈ 220 whp / 350 N·m.
- ``test_catalog_reference_curve`` (marcador ``accuracy``, fora do ``make check``): lê o
  catálogo real (``catalog/data``) e compara os 4 veículos com ``compare_to_reference``,
  passo de 250 rpm de 2000 rpm até à rotação máxima da curva.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import ReferenceCurvePoint, VehicleSpec
from simremap.physics.contracts import PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.physics.reference import ReferenceDriver

# Tabela A.4 (hatch-20t-gdi, stock-e27, η 0,85): rpm → (torque N·m, roda kW, λ, EGT °C).
HATCH_V1: dict[float, tuple[float, float, float, float]] = {
    2000: (350.0, 62.3, 0.95, 720),
    2500: (350.0, 77.9, 0.95, 760),
    3000: (350.0, 93.5, 0.95, 800),
    3500: (350.0, 109.0, 0.93, 840),
    4000: (350.0, 124.6, 0.90, 870),
    4500: (350.0, 140.2, 0.88, 890),
    5000: (345.0, 153.5, 0.85, 905),
    5500: (331.0, 162.0, 0.83, 915),
    6000: (307.3, 164.1, 0.82, 920),
    6500: (276.0, 159.7, 0.82, 925),
}


def _sweep(
    engine: PhysicsEngine,
    driver: ReferenceDriver,
    rpms: list[float],
    run_steady: Callable[..., Any],
) -> list[Any]:
    return [run_steady(engine, driver, r, 9.0 if i == 0 else 4.0) for i, r in enumerate(rpms)]


def test_hatch_fixture_full_load_sweep(
    make_engine: Callable[..., PhysicsEngine],
    hatch: VehicleSpec,
    run_steady: Callable[..., Any],
) -> None:
    engine = make_engine(hatch, noise_enabled=False, sim_hz=500)
    driver = ReferenceDriver(engine, hatch.reference_command_schedule)
    results = _sweep(engine, driver, list(HATCH_V1), run_steady)
    for res in results:
        torque, wheel_kw, lam, egt = HATCH_V1[res.rpm]
        assert res.torque_nm == pytest.approx(torque, rel=0.05), res.rpm
        assert res.wheel_kw == pytest.approx(wheel_kw, rel=0.05), res.rpm
        assert res.lambda_collector == pytest.approx(lam, rel=0.05), res.rpm
        assert res.egt_collector_c == pytest.approx(egt, rel=0.05), res.rpm
        # Ganchos do dano coerentes com os limites de série (120 bar, 330 °C).
        assert max(res.last.p_max_kpa) < 12_000.0
        assert max(res.last.piston_temp_c) < 330.0
    assert max(r.whp for r in results) == pytest.approx(220.0, rel=0.05)
    assert max(r.torque_nm for r in results) == pytest.approx(350.0, rel=0.05)


def _catalog() -> Any:
    try:
        from simremap.catalog.service import load_catalog

        return load_catalog(allow_drafts=True)
    except Exception:
        return None


CATALOG = _catalog()


@pytest.mark.accuracy
@pytest.mark.skipif(CATALOG is None, reason="catálogo real (catalog/data) indisponível")
@pytest.mark.parametrize(
    "vehicle_id", ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]
)
def test_catalog_reference_curve(vehicle_id: str, run_steady: Callable[..., Any]) -> None:
    """RNF-02: desvio < 5 % por ponto contra a ``ReferenceCurve`` v1 do catálogo."""
    from simremap.catalog.compare import compare_to_reference

    vehicle = CATALOG.get_vehicle(vehicle_id)
    fuel = CATALOG.get_fuel(vehicle.stock_fuel_id)
    curve = CATALOG.get_reference_curves(vehicle_id)[0]
    engine = PhysicsEngine(
        PhysicsConfig(sim_hz=500, noise_enabled=False), vehicle, fuel, initial_ect_c=90.0
    )
    driver = ReferenceDriver(engine, vehicle.reference_command_schedule)
    rpms = [p.rpm for p in curve.points if p.rpm >= 2000.0]
    results = _sweep(engine, driver, rpms, run_steady)
    simulated = [
        ReferenceCurvePoint(
            rpm=r.rpm,
            torque_crank_nm=max(r.torque_nm, 0.0),
            power_wheel_kw=max(r.wheel_kw, 0.0),
            lambda_value=min(max(r.lambda_collector, 0.6), 1.3),
            egt_c=min(max(r.egt_collector_c, 200.0), 1100.0),
        )
        for r in results
    ]
    comparison = compare_to_reference(curve, simulated)
    detail = {
        d.quantity: (round(d.max_deviation_pct, 1), d.rpm_at_max) for d in comparison.deviations
    }
    assert comparison.passed, detail
