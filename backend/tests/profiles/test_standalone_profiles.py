"""Perfis standalone ``ft-pro``, ``m1-race`` e ``ht-elite`` (T153; RF-04, RF-14 a RF-16)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.core.errors import SimRemapError
from simremap.ecu.calibration import CalibrationContent, parse_content
from simremap.ecu.service import validate_with_profile
from simremap.ecu.tables import Table3D
from simremap.physics.contracts import SensorReadings
from simremap.profiles.adapter import build_profiled_ecu
from simremap.profiles.contracts import BaseSetup, EcuProfileId, InjectorSetup, WizardInputs
from simremap.profiles.hooks.standalone import InjectorModel
from simremap.profiles.registry import get_registry
from simremap.profiles.setup import hardware_config
from simremap.profiles.wizard import _pulse_ms, generate_base_map, switch_fuel_model_mode

SensorFactory = Callable[..., SensorReadings]


@pytest.fixture
def classic_setup(
    base_payload: Callable[..., dict[str, Any]],
) -> BaseSetup:
    return BaseSetup.model_validate(base_payload())


def wizard_content(
    profile: EcuProfileId, base: BaseSetup, vehicle: VehicleSpec, **wiz: Any
) -> CalibrationContent:
    return generate_base_map(profile, base, vehicle, WizardInputs(**wiz)).content


def with_strategy(content: CalibrationContent, **strategies: dict[str, Any]) -> CalibrationContent:
    data = content.model_dump()
    for kind, cfg in strategies.items():
        data["strategies"][kind] = {"kind": kind, **cfg}
    return parse_content(data)


def test_oem_rejects_two_step(oem_content: Callable[..., CalibrationContent]) -> None:
    """RF-04: ``oem-stage`` com two-step ⇒ 422 ``STRATEGY_NOT_SUPPORTED_BY_PROFILE``."""
    content = with_strategy(oem_content(), two_step={})
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(content, get_registry().hooks_for("oem-stage"))
    assert exc.value.error_code == "STRATEGY_NOT_SUPPORTED_BY_PROFILE"


def test_ft_pro_rejects_torque_table(
    classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """RF-04: ``ft-pro`` com tabela ``torque_limit`` ⇒ 422 ``TABLE_NOT_SUPPORTED_BY_PROFILE``."""
    content = wizard_content(EcuProfileId.FT_PRO, classic_setup, vehicle("classic-20t-swap"))
    data = content.model_dump()
    data["tables"]["torque_limit"] = {
        "table_id": "torque_limit",
        "kind": "torque_limit",
        "unit": "N·m",
        "x": {"quantity": "rpm", "values": [1000.0, 7000.0]},
        "values": [300.0, 300.0],
    }
    bad = parse_content(data)
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(bad, get_registry().hooks_for("ft-pro"))
    assert exc.value.error_code == "TABLE_NOT_SUPPORTED_BY_PROFILE"
    assert exc.value.error_status == 422


def test_ft_pro_antilag_switch_only(
    classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """RF-14: ``antilag.activation = rolling`` ⇒ 422 ``STRATEGY_OPTION_NOT_SUPPORTED``."""
    content = wizard_content(EcuProfileId.FT_PRO, classic_setup, vehicle("classic-20t-swap"))
    hooks = get_registry().hooks_for("ft-pro")
    rolling = with_strategy(content, antilag={"activation": "rolling"})
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(rolling, hooks)
    assert exc.value.error_code == "STRATEGY_OPTION_NOT_SUPPORTED"
    validate_with_profile(with_strategy(content, antilag={"activation": "switch"}), hooks)
    disabled = with_strategy(content, antilag={"activation": "rolling", "enabled": False})
    validate_with_profile(disabled, hooks)


def test_fuel_mode_outside_profile(
    classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    content = wizard_content(EcuProfileId.FT_PRO, classic_setup, vehicle("classic-20t-swap"))
    data = content.model_dump()
    data["profile_id"] = "ht-elite"
    data.pop("profile_params", None)
    data["tables"].pop("inj_base_ms")
    data["fuel_model"]["mode"] = "speed_density_ve"
    ht_content = parse_content(data)
    assert get_registry().hooks_for("ht-elite").validate_calibration(ht_content, {}) == []
    data["fuel_model"]["mode"] = "profile_air_model"
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(parse_content(data), get_registry().hooks_for("ht-elite"))
    assert exc.value.error_code == "STRATEGY_OPTION_NOT_SUPPORTED"


def test_ft_pro_mode_switch_derives_ms_from_ve(
    classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """RF-14: trocar para ms gera ``inj_base_ms`` derivado do VE com erro < 1 %."""
    classic = vehicle("classic-20t-swap")
    ve_content = wizard_content(
        EcuProfileId.FT_PRO, classic_setup, classic, fuel_model_mode="speed_density_ve"
    )
    assert ve_content.fuel_model.mode == "speed_density_ve"
    assert "inj_base_ms" not in ve_content.tables
    hw = hardware_config(classic_setup, classic)
    ms = switch_fuel_model_mode(ve_content, "direct_pulse_ms", hw)
    assert ms.fuel_model.mode == "direct_pulse_ms"
    inj = ms.tables["inj_base_ms"]
    ve = ve_content.tables["ve"]
    lam = ve_content.tables["lambda_target"]
    assert isinstance(inj, Table3D) and isinstance(ve, Table3D) and isinstance(lam, Table3D)
    for i in (2, 8, 15):
        for j in (3, 9, 14):
            m, r = ve.y.values[i], ve.x.values[j]
            ref = _pulse_ms(hw, ve.values[i][j], m, lam.lookup(r, m), iat_c=30.0)
            assert inj.values[i][j] == pytest.approx(ref, rel=0.01)
    back = switch_fuel_model_mode(ms, "speed_density_ve", hw)
    assert back.fuel_model.mode == "speed_density_ve"
    validate_with_profile(ms, get_registry().hooks_for("ft-pro"))


def test_m1_race_package(classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]) -> None:
    """RF-15: pacote ``base`` com two-step ⇒ 422 ``STRATEGY_REQUIRES_PACKAGE``; ``race`` aceita."""
    classic = vehicle("classic-20t-swap")
    base_pkg = wizard_content(EcuProfileId.M1_RACE, classic_setup, classic)
    assert base_pkg.profile_params["feature_package"] == "base"
    assert base_pkg.fuel_model.charge_temp_blend == pytest.approx(0.25)
    hooks = get_registry().hooks_for("m1-race")
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(with_strategy(base_pkg, two_step={}), hooks)
    assert exc.value.error_code == "STRATEGY_REQUIRES_PACKAGE"
    with pytest.raises(SimRemapError) as exc2:
        validate_with_profile(with_strategy(base_pkg, antilag={}), hooks)
    assert exc2.value.error_code == "STRATEGY_REQUIRES_PACKAGE"
    race_setup = classic_setup.model_copy(update={"feature_package": "race"})
    race = wizard_content(EcuProfileId.M1_RACE, race_setup, classic)
    validate_with_profile(
        with_strategy(race, two_step={}, antilag={"activation": "rolling"}), hooks
    )
    with pytest.raises(SimRemapError):
        wizard_content(
            EcuProfileId.M1_RACE, classic_setup, classic, fuel_model_mode="direct_pulse_ms"
        )


def test_m1_short_pulse_adder(
    classic_setup: BaseSetup,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
    sensors: SensorFactory,
) -> None:
    """RF-15: pulso de 1,0 ms com adição de +0,08 ms a 1,0 ms ⇒ pulso físico +0,08 ms ± 0,001."""
    inj = InjectorSetup(
        flow_cc_min=2000.0,
        dead_time_ms=[0.9, 0.9],
        dead_time_v=[8.0, 16.0],
        short_pulse_ms=[0.5, 1.0, 2.0],
        short_pulse_adder_ms=[0.15, 0.08, 0.0],
    )
    model = InjectorModel(inj)
    assert model.active
    assert model.adjust(1.0, 0.9, 300.0) == pytest.approx(1.08, abs=0.001)
    assert model.adjust(0.0, 0.9, 300.0) == 0.0
    flow = InjectorModel(
        inj.model_copy(update={"flow_vs_dp_kpa": [200.0, 400.0], "flow_vs_dp_factor": [0.8, 1.2]})
    )
    # fator 1,0 a 300 kPa = sqrt(300/300) ⇒ só a adição de pulso curto
    assert flow.adjust(1.0, 0.9, 300.0) == pytest.approx(1.08, abs=0.001)
    assert flow.adjust(5.0, 0.9, 400.0) > 0.9
    # No laço: o pulso entregue à física soma a adição de pulso curto.
    classic = vehicle("classic-20t-swap")
    base = classic_setup.model_copy(update={"injectors": inj})
    content = wizard_content(EcuProfileId.M1_RACE, base, classic)
    ecu = build_profiled_ecu(
        vehicle=classic,
        stock_fuel=catalog.get_fuel("e100"),
        profile_id="m1-race",
        ecu_state="standalone_ready",
        base_setup=base,
        calibration=content,
    )
    res = ecu.step(sensors(rpm=900.0, map_kpa=35.0, tps_pct=2.0, pedal_pct=2.0), 0.001)
    commanded = res.status.injector_pw_ms[0]
    expected = commanded + InjectorModel(inj).adjust(commanded, 0.9, 300.0) - commanded
    assert res.commands.injector_pw_ms[0] == pytest.approx(expected, abs=0.02)
    assert res.commands.injector_pw_ms[0] > commanded


def test_ht_elite_rolling_antilag(
    classic_setup: BaseSetup, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """RF-16: ``antilag.activation = rolling`` é aceite no ``ht-elite``."""
    content = wizard_content(EcuProfileId.HT_ELITE, classic_setup, vehicle("classic-20t-swap"))
    validate_with_profile(
        with_strategy(content, antilag={"activation": "rolling"}),
        get_registry().hooks_for("ht-elite"),
    )
