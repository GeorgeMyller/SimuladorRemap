"""Flags OEM, checksum CRC32 e ``BaseSetup`` fixa do ``oem-stage`` (T152; RF-10 a RF-13)."""

from __future__ import annotations

import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.core.errors import SimRemapError
from simremap.ecu.calibration import (
    Calibration,
    CalibrationContent,
    CalibrationMetadata,
    build_calibration,
    compute_content_hash,
)
from simremap.ecu.service import validate_with_profile
from simremap.physics.contracts import SensorReadings
from simremap.profiles.adapter import ProfiledEcu, build_profiled_ecu
from simremap.profiles.contracts import OemProtectionFlags
from simremap.profiles.hardware import load_vehicle_hardware
from simremap.profiles.hooks.oem_stage import oem_checksum, oem_flags
from simremap.profiles.registry import get_registry
from simremap.profiles.setup import build_checklist, oem_base_setup

SensorFactory = Callable[..., SensorReadings]


def ecu(content: CalibrationContent, vehicle: VehicleSpec, catalog: CatalogService) -> ProfiledEcu:
    return build_profiled_ecu(
        vehicle=vehicle,
        stock_fuel=catalog.get_fuel(vehicle.stock_fuel_id),
        profile_id="oem-stage",
        ecu_state="oem",
        base_setup=None,
        calibration=content,
    )


def with_lambda(content: CalibrationContent, value: float) -> CalibrationContent:
    """Lambda alvo constante e ``lambda_component_protection(920 °C) = 0,82``."""
    data = content.model_dump()
    lam = data["tables"]["lambda_target"]
    lam["values"] = [[value] * len(row) for row in lam["values"]]
    lcp = data["tables"]["lambda_component_protection"]
    lcp["x"]["values"] = [600.0, 920.0, 950.0, 1000.0]
    lcp["values"] = [1.3, 0.82, 0.80, 0.78]
    return CalibrationContent.model_validate(data)


def calibration(content: CalibrationContent, checksum: str | None) -> Calibration:
    extra = {"oem_checksum": checksum} if checksum is not None else {}
    return build_calibration(
        content,
        calibration_id="c-91",
        version=4,
        parent_version=3,
        metadata=CalibrationMetadata(name="Stage 1", extra=extra),
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
    )


def test_flags_default_active() -> None:
    assert oem_flags({}) == OemProtectionFlags()
    flags = oem_flags({"knock_protection": False, "checksum_check": "x"})
    assert not flags.knock_protection and flags.checksum_check and flags.torque_monitoring


def test_component_protection_rf10(
    oem_content: Callable[..., CalibrationContent],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """EGT 920 °C e λ_cp(920) = 0,82 ⇒ alvo efetivo 0,82 com alvo 0,90; flag desligada ⇒ 0,90."""
    hatch = vehicle("hatch-20t-gdi")
    on = ecu(with_lambda(oem_content(), 0.90), hatch, catalog)
    lcp = with_lambda(oem_content(), 0.90).tables["lambda_component_protection"]
    assert lcp.lookup(920.0) == pytest.approx(0.82)  # type: ignore[call-arg]
    res = on.step(sensors(egt_collector_c=920.0, map_kpa=150.0), 0.001)
    assert res.status.lambda_target == pytest.approx(0.82)
    cold = on.step(sensors(egt_collector_c=600.0, map_kpa=150.0, t_sim_s=1.001), 0.001)
    assert cold.status.lambda_target == pytest.approx(0.90)
    off = ecu(with_lambda(oem_content(component_protection=False), 0.90), hatch, catalog)
    res_off = off.step(sensors(egt_collector_c=920.0, map_kpa=150.0), 0.001)
    assert res_off.status.lambda_target == pytest.approx(0.90)
    events = [e.kind for e in res_off.profile_events]
    assert events.count("oem_protection_disabled") == 1


def test_knock_and_overboost_protection_flags_rf11(
    oem_content: Callable[..., CalibrationContent],
    sensors: SensorFactory,
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
) -> None:
    """``knock_protection = false`` desliga o knock control e emite o evento 1 vez por aplicação."""
    hatch = vehicle("hatch-20t-gdi")
    knock = [0.9, 0.9, 0.9, 0.9]
    normal = ecu(oem_content(), hatch, catalog)
    for k in range(5):
        res = normal.step(
            sensors(knock_intensity=knock, map_kpa=200.0, t_sim_s=1.0 + 0.05 * k), 0.001
        )
    assert max(res.status.knock_retard_deg) > 0.0
    off = ecu(oem_content(knock_protection=False, overboost_protection=False), hatch, catalog)
    disabled: list[str] = []
    for k in range(5):
        res = off.step(sensors(knock_intensity=knock, map_kpa=330.0, t_sim_s=1.0 + 0.05 * k), 0.001)
        disabled += [e.detail for e in res.profile_events if e.kind == "oem_protection_disabled"]
    assert max(res.status.knock_retard_deg) == 0.0
    assert sorted(disabled) == ["knock_protection", "overboost_protection"]
    assert "failsafe" not in res.status.active_strategies or res.status.wastegate_duty_pct > 0.0
    runtime = off.runtime
    assert runtime is not None and not runtime.knock.enabled
    # Nova aplicação (calibração recompilada) ⇒ o evento volta a sair 1 vez.
    from simremap.ecu.compiled import compile_calibration

    runtime.swap_calibration(compile_calibration(oem_content(knock_protection=False), 4))
    res = off.step(sensors(t_sim_s=2.0), 0.001)
    assert [e.detail for e in res.profile_events] == ["knock_protection"]


def test_checksum_formula_matches_catalog(oem_payload: Callable[..., dict[str, Any]]) -> None:
    payload = oem_payload()
    h = payload["content_hash"]
    assert oem_checksum(h) == format(zlib.crc32(f"{h}:oem-stage".encode()), "08x")
    assert len(oem_checksum(h)) == 8


def test_checksum_invalid_rf12(oem_content: Callable[..., CalibrationContent]) -> None:
    """Checksum desatualizado ⇒ 422 ``OEM_CHECKSUM_INVALID`` com ``stored`` e ``expected``."""
    content = oem_content()
    hooks = get_registry().hooks_for("oem-stage")
    good = calibration(content, oem_checksum(compute_content_hash(content)))
    assert hooks.validate_calibration(good, {}) == []
    stale = calibration(content, "deadbeef")
    problems = hooks.validate_calibration(stale, {})
    assert problems[0][0] == "OEM_CHECKSUM_INVALID"
    expected = oem_checksum(stale.content_hash)
    assert "stored=deadbeef" in problems[0][1] and f"expected={expected}" in problems[0][1]
    with pytest.raises(SimRemapError) as exc:
        validate_with_profile(stale, hooks)
    assert exc.value.error_code == "OEM_CHECKSUM_INVALID" and exc.value.error_status == 422
    missing = calibration(content, None)
    assert "stored=ausente" in hooks.validate_calibration(missing, {})[0][1]
    # Correção automática e verificação desligada.
    assert hooks.validate_calibration(stale, {"auto_fix_checksum": True}) == []
    no_check = calibration(oem_content(checksum_check=False), "deadbeef")
    assert hooks.validate_calibration(no_check, {}) == []
    # Na criação (sem metadados) não há verificação.
    assert hooks.validate_calibration(content, {}) == []


def test_oem_base_setup_is_stock_rf13(
    vehicle: Callable[[str], VehicleSpec], catalog: CatalogService
) -> None:
    hatch = vehicle("hatch-20t-gdi")
    hw = load_vehicle_hardware("hatch-20t-gdi")
    assert hw is not None
    base = oem_base_setup(hatch, hw, catalog.get_fuel("e27"))
    assert base.trigger is not None and base.trigger.wheel == "60-2"
    assert base.trigger.firing_order == [1, 3, 4, 2]
    assert base.injectors is not None
    assert base.injectors.flow_cc_min == hatch.injectors.flow_cc_min
    assert base.fuel is not None and base.fuel.fuel_id == "e27"
    assert base.protection.rev_limit_rpm == hatch.mechanical_limits.rev_limit_rpm
    assert build_checklist(base, hw, base_map="ok").minimum_valid
    muscle = vehicle("muscle-v8-sc")
    hw_v8 = load_vehicle_hardware("muscle-v8-sc")
    assert hw_v8 is not None
    v8 = oem_base_setup(muscle, hw_v8, catalog.get_fuel("e27"))
    assert v8.injectors is not None and v8.injectors.fuel_pressure_mode == "map_referenced"
