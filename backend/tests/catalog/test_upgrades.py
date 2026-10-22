"""Oficina de upgrades: ``apply_upgrades`` e ``GET /api/v1/upgrades`` (002 RF-13 a RF-17; T010).

Cada peça altera só os seus parâmetros, o veículo continua a passar os validadores do
catálogo, peças incompatíveis dão 422 ``UPGRADE_NOT_COMPATIBLE`` e o pacote de série
devolve o mesmo veículo.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.errors import UpgradeNotCompatible
from simremap.catalog.service import CatalogService
from simremap.catalog.upgrades import (
    UPGRADE_CATEGORIES,
    UpgradePackage,
    apply_upgrades,
    upgrade_catalog,
)
from simremap.damage.mechanical import StructuralLimits

FULL = UpgradePackage(
    turbo="upgraded",
    injectors="high_flow",
    fuel_pump="high_flow",
    intercooler="sport",
    downpipe="high_flow",
    internals="forged",
)


@pytest.fixture
def hatch(service: CatalogService) -> VehicleSpec:
    return service.get_vehicle("hatch-20t-gdi")


@pytest.fixture
def muscle(service: CatalogService) -> VehicleSpec:
    return service.get_vehicle("muscle-v8-sc")


def test_stock_package_is_identity(hatch: VehicleSpec) -> None:
    result = apply_upgrades(hatch, UpgradePackage())
    assert result.vehicle is hatch
    assert result.physics.exhaust_backpressure_scale == 1.0
    assert result.physics.fuel_pump_capacity_scale == 1.0
    assert UpgradePackage().is_stock and UpgradePackage().non_stock() == {}


def test_turbo_upgraded(hatch: VehicleSpec) -> None:
    new = apply_upgrades(hatch, UpgradePackage(turbo="upgraded")).vehicle
    assert hatch.turbo is not None and new.turbo is not None
    old_c, new_c = hatch.turbo.compressor, new.turbo.compressor
    assert new.turbo.turbine_area_eff_cm2 == pytest.approx(hatch.turbo.turbine_area_eff_cm2 * 1.25)
    assert new.turbo.rotor_inertia_kg_m2 == pytest.approx(hatch.turbo.rotor_inertia_kg_m2 * 1.45)
    assert new_c.m_choke_max_kg_s == pytest.approx(old_c.m_choke_max_kg_s * 1.30)
    assert new_c.m_peak_kg_s > old_c.m_peak_kg_s and new_c.n_peak_rpm > old_c.n_peak_rpm
    assert new_c.n_peak_rpm <= new_c.n_max_rpm
    assert new.injectors == hatch.injectors and new.engine == hatch.engine


def test_injectors_and_pump(hatch: VehicleSpec) -> None:
    result = apply_upgrades(hatch, UpgradePackage(injectors="high_flow", fuel_pump="high_flow"))
    assert result.vehicle.injectors.flow_cc_min == pytest.approx(hatch.injectors.flow_cc_min * 1.5)
    assert result.physics.fuel_pump_capacity_scale == pytest.approx(1.8)
    assert result.vehicle.injectors.dead_time_ms == hatch.injectors.dead_time_ms


def test_intercooler_sport_is_capped(hatch: VehicleSpec) -> None:
    assert hatch.engine.intercooler is not None
    new = apply_upgrades(hatch, UpgradePackage(intercooler="sport")).vehicle
    assert new.engine.intercooler is not None
    expected = min(hatch.engine.intercooler.effectiveness + 0.08, 0.95)
    assert new.engine.intercooler.effectiveness == pytest.approx(expected)
    capped = hatch.model_copy(
        update={
            "engine": hatch.engine.model_copy(
                update={
                    "intercooler": hatch.engine.intercooler.model_copy(
                        update={"effectiveness": 0.92}
                    )
                }
            )
        }
    )
    top = apply_upgrades(capped, UpgradePackage(intercooler="sport")).vehicle
    assert top.engine.intercooler is not None
    assert top.engine.intercooler.effectiveness == pytest.approx(0.95)


def test_downpipe(hatch: VehicleSpec) -> None:
    result = apply_upgrades(hatch, UpgradePackage(downpipe="high_flow"))
    assert result.physics.exhaust_backpressure_scale == pytest.approx(0.6)
    assert result.vehicle is hatch


def test_forged_internals_raise_limits(hatch: VehicleSpec) -> None:
    new = apply_upgrades(hatch, UpgradePackage(internals="forged")).vehicle
    old_l, new_l = hatch.mechanical_limits, new.mechanical_limits
    assert new_l.max_rod_load_kn == pytest.approx(old_l.max_rod_load_kn * 1.35)
    assert new_l.max_cylinder_pressure_bar == pytest.approx(old_l.max_cylinder_pressure_bar * 1.25)
    assert new_l.max_piston_temp_c == pytest.approx(old_l.max_piston_temp_c + 40.0)
    assert new_l.rod_torque_limit_nm == pytest.approx(old_l.rod_torque_limit_nm * 1.35)
    limits = StructuralLimits.from_vehicle(new)
    assert limits.rod_force_limit_n == pytest.approx(1000.0 * new_l.max_rod_load_kn)
    assert limits.cylinder_pressure_limit_kpa == pytest.approx(
        100.0 * new_l.max_cylinder_pressure_bar
    )


@pytest.mark.parametrize(
    "vehicle_id", ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]
)
def test_full_package_passes_validators(service: CatalogService, vehicle_id: str) -> None:
    vehicle = service.get_vehicle(vehicle_id)
    pkg = FULL if vehicle.turbo is not None else FULL.model_copy(update={"turbo": "stock"})
    new = apply_upgrades(vehicle, pkg).vehicle
    assert VehicleSpec.model_validate(new.model_dump()) == new
    assert new.mechanical_limits.rod_torque_limit_nm > new.rated.peak_torque_nm


def test_turbo_on_supercharged_is_incompatible(muscle: VehicleSpec) -> None:
    with pytest.raises(UpgradeNotCompatible) as info:
        apply_upgrades(muscle, UpgradePackage(turbo="upgraded"))
    err = info.value
    assert err.error_code == "UPGRADE_NOT_COMPATIBLE" and err.error_status == 422
    assert err.extra["category"] == "turbo" and err.extra["part_id"] == "upgraded"


def test_intercooler_without_intercooler_is_incompatible(hatch: VehicleSpec) -> None:
    bare = hatch.model_copy(
        update={"engine": hatch.engine.model_copy(update={"intercooler": None})}
    )
    with pytest.raises(UpgradeNotCompatible) as info:
        apply_upgrades(bare, UpgradePackage(intercooler="sport"))
    assert info.value.extra["category"] == "intercooler"


def test_package_rejects_unknown_part() -> None:
    with pytest.raises(ValidationError):
        UpgradePackage.model_validate({"turbo": "big"})
    with pytest.raises(ValidationError):
        UpgradePackage.model_validate({"exhaust": "stock"})


def test_catalog_lists_six_categories() -> None:
    cat = upgrade_catalog()
    assert [c.category for c in cat.categories] == list(UPGRADE_CATEGORIES)
    for category in cat.categories:
        assert category.options[0].part_id == "stock"
        expected = 4 if category.category == "turbo" else 2
        assert len(category.options) == expected
        assert all(option.effects for option in category.options[1:])


async def test_upgrades_endpoint(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/upgrades")
    assert resp.status_code == 200
    body = resp.json()
    assert [c["category"] for c in body["categories"]] == list(UPGRADE_CATEGORIES)
    turbo = body["categories"][0]["options"]
    assert turbo[0] == {"part_id": "stock", "label": "Série", "effects": {}}
    assert turbo[1]["part_id"] == "upgraded" and turbo[1]["label"] == "Turbina upgraded (Stage 1)"
    assert [o["part_id"] for o in turbo] == ["stock", "upgraded", "stage2", "stage3"]


def test_turbo_stages_grow_flow_and_lag(hatch: VehicleSpec) -> None:
    turbos = [
        apply_upgrades(hatch, UpgradePackage(turbo=part)).vehicle.turbo
        for part in ("stock", "upgraded", "stage2", "stage3")
    ]
    assert all(t is not None for t in turbos)
    chokes = [t.compressor.m_choke_max_kg_s for t in turbos if t is not None]
    areas = [t.turbine_area_eff_cm2 for t in turbos if t is not None]
    inertias = [t.rotor_inertia_kg_m2 for t in turbos if t is not None]
    for values in (chokes, areas, inertias):
        assert values == sorted(values) and len(set(values)) == 4
    stage3 = turbos[3]
    assert stage3 is not None and hatch.turbo is not None
    assert stage3.compressor.m_choke_max_kg_s == pytest.approx(
        2.0 * hatch.turbo.compressor.m_choke_max_kg_s
    )
    assert stage3.wastegate_area_max_cm2 == pytest.approx(1.3 * hatch.turbo.wastegate_area_max_cm2)


def test_turbo_stage_not_compatible_with_supercharger(muscle: VehicleSpec) -> None:
    with pytest.raises(UpgradeNotCompatible) as exc:
        apply_upgrades(muscle, UpgradePackage(turbo="stage3"))
    assert exc.value.extra["part_id"] == "stage3"
