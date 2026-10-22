"""Combustível flex ``blend_fuel`` (002 RF-18; T009, T022).

AFR, PCI e RON monotônicos entre E27 e E100, âncoras exatas, limites 27–100 %,
cache do solver separada por blend e sensor de etanol na física.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from simremap.catalog.contracts import FUEL_IDS, FuelSpec, VehicleSpec
from simremap.ecu.limits import (
    FLEX_AFR_E27,
    FLEX_AFR_E100,
    FLEX_DENSITY_E27_G_CC,
    FLEX_DENSITY_E100_G_CC,
)
from simremap.physics.contracts import PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.physics.errors import PhysicsError
from simremap.physics.fuel_blend import blend_afr_stoich, blend_fuel, blend_weight

PCTS = [27.0, 40.0, 50.0, 60.0, 85.0, 100.0]
CATALOG_FUELS = Path(__file__).parents[2] / "src" / "simremap" / "catalog" / "data" / "fuels"


@pytest.fixture
def anchors(fuels: dict[str, FuelSpec]) -> tuple[FuelSpec, FuelSpec]:
    return fuels["e27"], fuels["e100"]


def test_anchors_reproduce_catalog_fuels(anchors: tuple[FuelSpec, FuelSpec]) -> None:
    e27, e100 = anchors
    low, high = blend_fuel(e27, e100, 27.0), blend_fuel(e27, e100, 100.0)
    for name in ("afr_stoich", "lhv_mj_kg", "ron", "mon", "h_fg_kj_kg", "density_kg_m3"):
        assert getattr(low, name) == pytest.approx(getattr(e27, name)), name
        assert getattr(high, name) == pytest.approx(getattr(e100, name)), name
    assert low.fuel_id == high.fuel_id == "flex"
    assert low.ethanol_mass_fraction == pytest.approx(e27.ethanol_mass_fraction)


def test_properties_are_monotonic(anchors: tuple[FuelSpec, FuelSpec]) -> None:
    e27, e100 = anchors
    blends = [blend_fuel(e27, e100, pct) for pct in PCTS]
    afr = [b.afr_stoich for b in blends]
    lhv = [b.lhv_mj_kg for b in blends]
    ron = [b.ron for b in blends]
    assert afr == sorted(afr, reverse=True) and len(set(afr)) == len(afr)
    assert lhv == sorted(lhv, reverse=True)
    assert ron == sorted(ron)
    assert [b.h_fg_kj_kg for b in blends] == sorted(b.h_fg_kj_kg for b in blends)


def test_e50_between_anchors_and_reciprocal_afr(anchors: tuple[FuelSpec, FuelSpec]) -> None:
    e27, e100 = anchors
    e50 = blend_fuel(e27, e100, 50.0)
    assert e100.afr_stoich < e50.afr_stoich < e27.afr_stoich
    t = blend_weight(50.0)
    assert 1.0 / e50.afr_stoich == pytest.approx((1 - t) / e27.afr_stoich + t / e100.afr_stoich)
    assert e50.lhv_mj_kg == pytest.approx(e27.lhv_mj_kg + t * (e100.lhv_mj_kg - e27.lhv_mj_kg))


def test_ron_curve_is_concave(anchors: tuple[FuelSpec, FuelSpec]) -> None:
    e27, e100 = anchors
    mid = blend_fuel(e27, e100, (27.0 + 100.0) / 2)
    assert mid.ron > (e27.ron + e100.ron) / 2
    assert mid.mon > (e27.mon + e100.mon) / 2


@pytest.mark.parametrize("pct", [26.9, 100.1, 0.0, -5.0])
def test_limits(anchors: tuple[FuelSpec, FuelSpec], pct: float) -> None:
    e27, e100 = anchors
    with pytest.raises(ValueError, match="ethanol_pct"):
        blend_fuel(e27, e100, pct)


def test_ecu_flex_anchors_match_catalog() -> None:
    """As âncoras do sensor flex da ECU são o AFR de E27 e E100 do catálogo."""
    e27 = json.loads((CATALOG_FUELS / "e27.json").read_text(encoding="utf-8"))
    e100 = json.loads((CATALOG_FUELS / "e100.json").read_text(encoding="utf-8"))
    assert (FLEX_AFR_E27, FLEX_AFR_E100) == (e27["afr_stoich"], e100["afr_stoich"])
    assert (FLEX_DENSITY_E27_G_CC, FLEX_DENSITY_E100_G_CC) == (
        e27["density_kg_m3"] / 1000.0,
        e100["density_kg_m3"] / 1000.0,
    )
    assert blend_afr_stoich(85.0, FLEX_AFR_E27, FLEX_AFR_E100) == pytest.approx(
        blend_fuel(FuelSpec(**e27), FuelSpec(**e100), 85.0).afr_stoich
    )


def test_solver_cache_index_per_blend(
    classic: VehicleSpec, fuels: dict[str, FuelSpec], anchors: tuple[FuelSpec, FuelSpec]
) -> None:
    e27, e100 = anchors
    engine = PhysicsEngine(
        PhysicsConfig(noise_enabled=False), classic, blend_fuel(e27, e100, 85.0), ethanol_pct=85.0
    )
    solver = engine.solver
    i85 = engine.fuel_index
    i50 = solver.register_fuel(blend_fuel(e27, e100, 50.0))
    assert i85 >= len(FUEL_IDS) and i50 >= len(FUEL_IDS) and i85 != i50
    assert solver.register_fuel(blend_fuel(e27, e100, 85.0)) == i85
    assert solver.register_fuel(fuels["e100"]) == FUEL_IDS.index("e100")


def test_engine_publishes_ethanol_sensor(
    classic: VehicleSpec,
    anchors: tuple[FuelSpec, FuelSpec],
    make_engine: Callable[..., PhysicsEngine],
) -> None:
    e27, e100 = anchors
    flex = blend_fuel(e27, e100, 85.0)
    quiet = PhysicsEngine(PhysicsConfig(noise_enabled=False), classic, flex, ethanol_pct=85.0)
    assert quiet.read_sensors().ethanol_pct == 85.0
    noisy = PhysicsEngine(PhysicsConfig(seed=3), classic, flex, ethanol_pct=85.0)
    reading = noisy.read_sensors().ethanol_pct
    assert reading is not None and abs(reading - 85.0) <= 0.3
    assert make_engine(classic).read_sensors().ethanol_pct is None
    with pytest.raises(PhysicsError):
        PhysicsEngine(PhysicsConfig(), classic, flex)
