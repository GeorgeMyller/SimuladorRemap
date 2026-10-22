"""Registo dos 4 perfis, descritores e matriz de suporte (T150; RF-01 a RF-04, RF-14 a RF-16)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.core.errors import SimRemapError
from simremap.ecu.contracts import StrategyKind
from simremap.profiles.contracts import EcuProfileId, NavItem
from simremap.profiles.descriptors import DESCRIPTOR_BUILDERS, PROFILE_ORDER, AxisSet
from simremap.profiles.registry import (
    ProfileRegistry,
    RegistryHooksProvider,
    RegistryInvalid,
    axes_for_vehicle,
    build_registry,
    for_package,
    get_registry,
    validate_descriptor,
)

ORDER = ["oem-stage", "ft-pro", "m1-race", "ht-elite"]


def test_four_profiles_in_fixed_order() -> None:
    reg = get_registry()
    assert [p.value for p in reg.profile_ids] == ORDER
    names = [s.name for s in reg.summaries()]
    assert names == ["OEM-Stage", "FT-Pro", "M1-Race", "HT-Elite"]
    assert [s.family.value for s in reg.summaries()] == [
        "oem",
        "standalone",
        "standalone",
        "standalone",
    ]
    assert all(s.descriptor_version == "1.0.0" for s in reg.summaries())
    assert [s.profile_id.value for s in reg.summaries(frozenset({"ft-pro"}))] == ["ft-pro"]


def test_descriptors_are_complete() -> None:
    reg = get_registry()
    for pid in PROFILE_ORDER:
        desc = reg.get(pid)
        assert desc.navigation, pid
        assert sorted(s.kind for s in desc.strategies) == sorted(StrategyKind)
        assert desc.live_tunable_table_ids
        assert desc.accent_color.startswith("#")
        assert desc.terminology
        table_kinds = {t.kind.value for t in desc.tables}
        for section in desc.navigation:
            for item in section.items:
                if item.kind == "table":
                    assert item.target_id in table_kinds
    oem = reg.get("oem-stage")
    assert oem.load_axis_channel == "load_pct" and oem.accent_color == "#6B7A8F"
    assert oem.display_units.pressure == "bar_rel" and not oem.requires_base_setup
    assert [s.label for s in oem.navigation] == [
        "Pedido de torque",
        "Limitação de torque",
        "Ignição e eficiência",
        "Pressão alvo do turbo",
        "Mistura e proteção de componentes",
        "Overrun",
        "Proteções e checksum",
        "Comando variável (VVT)",
        "Flex (teor de etanol)",
    ]
    assert reg.get("ft-pro").base_setup_steps == [
        "trigger",
        "injectors",
        "fuel",
        "sensors",
        "protection",
        "review",
    ]
    assert reg.get("ht-elite").display_units.mixture == "afr"
    assert reg.get("m1-race").terminology["ve"] == "Eficiência do motor"


def test_support_matrix_appendix_b() -> None:
    m = get_registry().matrix()
    assert m["oem-stage"]["two_step"] == "unsupported"
    assert m["oem-stage"]["antilag"] == "unsupported"
    assert m["oem-stage"]["powershift"] == "unsupported"
    assert m["oem-stage"]["overrun"] == "supported"
    assert all(m["ft-pro"][k.value] == "supported" for k in StrategyKind)
    assert {k for k, v in m["m1-race"].items() if v == "package_race"} == {
        "two_step",
        "antilag",
        "powershift",
    }
    assert all(m["ht-elite"][k.value] == "supported" for k in StrategyKind)
    hooks = get_registry().hooks_for("oem-stage")
    assert "two_step" not in hooks.supported_strategies()
    assert "antilag" in get_registry().hooks_for("m1-race").supported_strategies()


def test_nav_target_not_supported_fails_registry() -> None:
    """RF-03: ``NavItem`` com ``antilag`` no ``oem-stage`` ⇒ ``NAV_TARGET_NOT_SUPPORTED``."""
    desc = get_registry().get("oem-stage")
    bad_item = NavItem(id="bad.antilag", label="Antilag", kind="strategy", target_id="antilag")
    section = desc.navigation[0].model_copy(update={"items": [bad_item]})
    bad = desc.model_copy(update={"navigation": [section]})
    with pytest.raises(RegistryInvalid) as exc:
        validate_descriptor(bad)
    assert exc.value.code == "NAV_TARGET_NOT_SUPPORTED"
    with pytest.raises(RegistryInvalid):
        ProfileRegistry({EcuProfileId.OEM_STAGE: bad})
    table_item = NavItem(id="bad.table", label="X", kind="table", target_id="inj_base_ms")
    with pytest.raises(RegistryInvalid):
        validate_descriptor(
            desc.model_copy(
                update={"navigation": [section.model_copy(update={"items": [table_item]})]}
            )
        )


def test_race_items_must_be_marked() -> None:
    desc = get_registry().get("m1-race")
    item = NavItem(id="x.two", label="Largada", kind="strategy", target_id="two_step")
    section = desc.navigation[0].model_copy(update={"items": [item]})
    with pytest.raises(RegistryInvalid, match="requires_package"):
        validate_descriptor(desc.model_copy(update={"navigation": [section]}))


def test_registry_rejects_wrong_order_and_blocked_terms() -> None:
    reg = build_registry()
    descs = dict(reg.descriptors)
    with pytest.raises(RegistryInvalid):
        ProfileRegistry(dict(reversed(list(descs.items()))))
    branded = descs[EcuProfileId.FT_PRO].model_copy(update={"inspiration": "Igual a uma Haltech"})
    with pytest.raises(RegistryInvalid) as exc:
        validate_descriptor(branded)
    assert exc.value.code == "PROFILE_REGISTRY_INVALID"


def test_unknown_profile_is_404() -> None:
    with pytest.raises(SimRemapError) as exc:
        get_registry().resolve("xx-pro")
    assert exc.value.error_code == "ECU_PROFILE_NOT_FOUND"
    assert exc.value.error_status == 404


def test_default_axes_and_vehicle_axes(vehicle: Callable[[str], VehicleSpec]) -> None:
    """RF-02: sem veículo RPM 500..8000 em 16 pontos; com veículo, último = rev_limit."""
    reg = get_registry()
    ft = reg.descriptor_for("ft-pro")
    ve = next(t for t in ft.tables if t.kind.value == "ve")
    assert ve.default_x.values[0] == 500.0 and ve.default_x.values[-1] == 8000.0
    assert len(ve.default_x.values) == 16
    assert ve.default_y is not None and ve.default_y.values == [20.0 * i for i in range(1, 17)]
    classic = vehicle("classic-20t-swap")
    ft_v = reg.descriptor_for("ft-pro", classic)
    ve_v = next(t for t in ft_v.tables if t.kind.value == "ve")
    assert ve_v.default_x.values[-1] == round(classic.mechanical_limits.rev_limit_rpm / 100) * 100
    assert ve_v.default_y is not None and ve_v.default_y.values[-1] >= 320.0
    hatch = reg.descriptor_for("oem-stage", vehicle("hatch-20t-gdi"))
    assert hatch.tables[0].default_x.values[-1] == 6500.0
    load = next(t for t in hatch.tables if t.kind.value == "torque_optimal").default_y
    assert load is not None and load.values[0] == 10.0 and load.values[-1] == 250.0
    pedal = next(t for t in hatch.tables if t.kind.value == "torque_request").default_y
    assert pedal is not None and pedal.values[:4] == [0.0, 2.0, 5.0, 10.0]
    assert axes_for_vehicle(vehicle("muscle-v8-sc")).n_cyl == 8
    assert axes_for_vehicle(None) == AxisSet()


def test_ft_pro_drag_section() -> None:
    """RF-14: secção "Funções de arrancada" com two-step, powershift, antilag e boost."""
    ft = get_registry().get("ft-pro")
    drag = next(s for s in ft.navigation if s.label == "Funções de arrancada")
    targets = {i.target_id for i in drag.items if i.kind == "strategy"}
    assert {"two_step", "powershift", "antilag", "boost_control"} <= targets
    assert ft.fuel_model_modes == ["direct_pulse_ms", "speed_density_ve"]
    antilag = next(s for s in ft.strategies if s.kind.value == "antilag")
    assert antilag.restricted_options == {"activation": ["switch"]}


def test_m1_race_package_filter() -> None:
    """RF-15: com pacote base o descritor omite a secção de competição."""
    reg = get_registry()
    full = reg.descriptor_for("m1-race")
    assert any(s.label == "Funções: competição" for s in full.navigation)
    base = reg.descriptor_for("m1-race", feature_package="base")
    assert all(s.label != "Funções: competição" for s in base.navigation)
    race = reg.descriptor_for("m1-race", feature_package="race")
    assert race == full
    ft = reg.get("ft-pro")
    assert for_package(ft, "base") == ft


def test_ht_elite_wizard_first_and_trims(vehicle: Callable[[str], VehicleSpec]) -> None:
    """RF-16: o assistente é o 1.º item e há trims por cilindro de 1 a ``n_cyl``."""
    reg = get_registry()
    ht = reg.descriptor_for("ht-elite", vehicle("coupe-30t-i6"))
    first = ht.navigation[0].items[0]
    assert first.kind == "base_setup" and first.target_id == "wizard"
    cyl = next(s for s in ht.navigation if s.label == "Correções por cilindro")
    fuel = [i.cylinder for i in cyl.items if i.target_id == "fuel_trim_cyl"]
    ign = [i.cylinder for i in cyl.items if i.target_id == "ignition_trim_cyl"]
    assert fuel == ign == list(range(1, 7))
    assert len(next(s for s in reg.get("ht-elite").navigation if s.id == "cylinders").items) == 16


def test_hooks_provider_and_runtime_hooks() -> None:
    provider = RegistryHooksProvider()
    assert provider.hooks_for("ft-pro").profile_id == "ft-pro"
    a = get_registry().runtime_hooks("oem-stage", 0.000496)
    b = get_registry().runtime_hooks("oem-stage", 0.000496)
    assert a is not b
    assert set(DESCRIPTOR_BUILDERS) == set(PROFILE_ORDER)
    assert get_registry().family("m1-race") == "standalone"


OEM_VEHICLES = ("hatch-20t-gdi", "coupe-30t-i6", "classic-20t-swap", "muscle-v8-sc")
OPTIONAL_OEM_SECTIONS = frozenset({"cams", "flex"})  # VVT e flex: só com o hardware


@pytest.mark.parametrize("vehicle_id", OEM_VEHICLES)
def test_oem_navigation_reaches_factory_tables(
    catalog: CatalogService, vehicle: Callable[[str], VehicleSpec], vehicle_id: str
) -> None:
    """003 T032: cada item de tabela do OEM-Stage abre uma tabela da calibração de série do
    veículo (antes: "Avanço cil. 1–n" sem ``ignition_trim_cyl`` na série e "cil. 5–8" no
    descritor genérico de um motor de 4 cilindros)."""
    payload = catalog.get_factory_calibration_payload(vehicle_id, "oem-stage")
    assert payload is not None
    present = {(t["kind"], t.get("cylinder")) for t in payload["tables"].values()}
    reg = get_registry()
    n_cyl = vehicle(vehicle_id).engine.n_cyl
    for desc in (
        reg.descriptor_for("oem-stage"),
        reg.descriptor_for("oem-stage", vehicle(vehicle_id)),
    ):
        for section in desc.navigation:
            if section.id in OPTIONAL_OEM_SECTIONS:
                continue
            for item in section.items:
                if item.kind != "table":
                    continue
                assert item.cylinder is None or item.cylinder <= n_cyl, item.id
                assert (item.target_id, item.cylinder) in present, (vehicle_id, item.id)
