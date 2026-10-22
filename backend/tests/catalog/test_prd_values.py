"""RF-05 e RF-06: 31 valores do PRD com proveniência ``prd`` e ``estimated_fields``."""

from __future__ import annotations

from typing import Any

import pytest

from simremap.catalog.contracts import ProvenanceKind
from simremap.catalog.loader import Catalog
from simremap.catalog.provenance import (
    effective_provenance,
    estimated_fields,
    numeric_field_pointers,
    resolve_pointer,
)

# Apêndice A.1 da spec vehicle-catalog (31 valores).
PRD_VALUES: list[tuple[str, str, Any]] = [
    ("hatch-20t-gdi", "/engine/displacement_cc", 1984),
    ("hatch-20t-gdi", "/engine/n_cyl", 4),
    ("hatch-20t-gdi", "/engine/compression_ratio", 9.6),
    ("hatch-20t-gdi", "/rated/peak_power_whp", 220),
    ("hatch-20t-gdi", "/rated/peak_torque_nm", 350),
    ("hatch-20t-gdi", "/mechanical_limits/rod_torque_limit_nm", 420),
    ("hatch-20t-gdi", "/mechanical_limits/egt_max_c", 950),
    ("hatch-20t-gdi", "/induction", "turbo"),
    ("hatch-20t-gdi", "/stock_profile_id", "oem-stage"),
    ("coupe-30t-i6", "/engine/displacement_cc", 2998),
    ("coupe-30t-i6", "/engine/n_cyl", 6),
    ("coupe-30t-i6", "/engine/architecture", "inline"),
    ("coupe-30t-i6", "/engine/compression_ratio", 10.2),
    ("coupe-30t-i6", "/rated/peak_power_whp", 340),
    ("coupe-30t-i6", "/rated/power_ceiling_whp", 750),
    ("coupe-30t-i6", "/mechanical_limits/egt_max_c", 980),
    ("coupe-30t-i6", "/induction", "turbo"),
    ("coupe-30t-i6", "/turbo/housing", "twin_scroll"),  # "um único turbo" (A.1 + A.3)
    ("classic-20t-swap", "/engine/displacement_cc", 1984),
    ("classic-20t-swap", "/engine/n_cyl", 4),
    ("classic-20t-swap", "/engine/compression_ratio", 8.5),
    ("classic-20t-swap", "/turbo/compressor_ar", 0.50),
    ("classic-20t-swap", "/turbo/turbine_ar", 0.63),
    ("classic-20t-swap", "/stock_fuel_id", "e100"),
    ("classic-20t-swap", "/rated/power_range_whp", (300, 600)),
    ("muscle-v8-sc", "/engine/displacement_cc", 4951),
    ("muscle-v8-sc", "/engine/n_cyl", 8),
    ("muscle-v8-sc", "/engine/architecture", "v"),
    ("muscle-v8-sc", "/induction", "supercharger"),
    ("muscle-v8-sc", "/rated/peak_power_whp", 460),
    ("muscle-v8-sc", "/rated/power_ceiling_whp", 800),
]


def test_thirty_one_values() -> None:
    assert len(PRD_VALUES) == 31


@pytest.mark.parametrize(("vehicle_id", "pointer", "expected"), PRD_VALUES)
def test_prd_value_and_provenance(
    real_catalog: Catalog, vehicle_id: str, pointer: str, expected: Any
) -> None:
    spec = real_catalog.vehicles[vehicle_id].spec
    assert resolve_pointer(spec, pointer) == expected
    prov = spec.provenance.get(pointer)
    assert prov is not None, f"{vehicle_id}{pointer} sem proveniência"
    assert prov.kind == ProvenanceKind.PRD


def test_single_turbo_coupe(real_catalog: Catalog) -> None:
    spec = real_catalog.vehicles["coupe-30t-i6"].spec
    assert spec.turbo is not None
    assert spec.supercharger is None


def test_estimated_fields_hatch(real_catalog: Catalog) -> None:
    entry = real_catalog.vehicles["hatch-20t-gdi"]
    fields = list(entry.estimated_fields)
    assert "/engine/rod_length_mm" in fields
    assert "/engine/bore_mm" not in fields
    assert "/engine/mbt_reference" in fields  # RF-26
    assert "/engine/true_ve" in fields
    assert "/engine/displacement_cc" not in fields
    assert "/engine/friction" not in fields  # literature
    assert fields == sorted(fields)
    assert fields == estimated_fields(entry.spec)


@pytest.mark.parametrize(
    "vehicle_id", ["hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc"]
)
def test_every_numeric_field_is_documented_or_estimated(
    real_catalog: Catalog, vehicle_id: str
) -> None:
    spec = real_catalog.vehicles[vehicle_id].spec
    estimated = set(real_catalog.vehicles[vehicle_id].estimated_fields)
    for pointer in numeric_field_pointers(spec):
        prov = effective_provenance(spec.provenance, pointer)
        documented = prov is not None and prov.kind in {"prd", "public_spec", "literature"}
        assert documented != (pointer in estimated), pointer
    assert "/data_version" not in estimated
    assert not any("calc_displacement_cc" in p for p in estimated)


def test_turbo_absent_on_supercharger(real_catalog: Catalog) -> None:
    fields = real_catalog.vehicles["muscle-v8-sc"].estimated_fields
    assert not any(p.startswith("/turbo") for p in fields)
    assert "/supercharger/displacement_l_per_rev" in fields
