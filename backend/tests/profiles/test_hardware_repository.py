"""Hardware por veículo, ficha, repositório e arranque do registo (T056-T058, T320, T329)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.catalog.contracts import VehicleSpec
from simremap.core.errors import SimRemapError
from simremap.profiles import registry as registry_mod
from simremap.profiles import router as router_mod
from simremap.profiles.contracts import BaseSetup, HardwareOverride, SwapResult
from simremap.profiles.hardware import (
    default_vehicle_hardware,
    hardware_sheet,
    load_vehicle_hardware,
    real_hardware,
)
from simremap.profiles.registry import RegistryInvalid
from simremap.profiles.repository import EcuSessionState, ProfileRepository
from simremap.profiles.setup import build_checklist
from simremap.profiles.swap import SwapIdempotency, plan_swap

VEHICLES = ("classic-20t-swap", "coupe-30t-i6", "hatch-20t-gdi", "muscle-v8-sc")


@pytest.mark.parametrize("vehicle_id", VEHICLES)
def test_hardware_files_match_catalog(
    vehicle_id: str, vehicle: Callable[[str], VehicleSpec]
) -> None:
    """T056: ``data/hardware/<vehicle_id>.json`` coerente com o vehicle-catalog."""
    hw = load_vehicle_hardware(vehicle_id)
    spec = vehicle(vehicle_id)
    assert hw is not None and hw.swap_supported
    assert hw.vehicle_id == vehicle_id
    assert hw.trigger_wheel == spec.engine.crank_trigger
    assert hw.firing_order == spec.engine.firing_order
    assert hw.tdc_offset_true_deg == hw.tdc_offset_nominal_deg
    sheet = hardware_sheet(hw, spec)
    assert sheet.n_cyl == spec.engine.n_cyl
    assert sheet.tank_fuel_id == spec.stock_fuel_id
    assert "tdc_offset_true" not in sheet.model_dump_json()


def test_missing_hardware_file_ec14(vehicle: Callable[[str], VehicleSpec]) -> None:
    load_vehicle_hardware.cache_clear()
    assert load_vehicle_hardware("nao-existe") is None
    assert load_vehicle_hardware("../etc") is None
    assert load_vehicle_hardware("") is None
    fallback = default_vehicle_hardware(vehicle("hatch-20t-gdi"))
    assert fallback.swap_supported is False and fallback.trigger_wheel == "60-2"


def test_real_hardware_override(vehicle: Callable[[str], VehicleSpec]) -> None:
    hw = load_vehicle_hardware("classic-20t-swap")
    assert hw is not None
    spec = vehicle("classic-20t-swap")
    ov = HardwareOverride(
        tdc_offset_shift_deg=-5.0,
        trigger_wheel="36-2",
        injector_flow_cc_min=900.0,
        map_sensor_kpa=(20.0, 300.0),
        tank_fuel_id="e27",
    )
    real = real_hardware(hw, spec, ov)
    assert real.tdc_offset_deg == 85.0 and real.trigger_wheel == "36-2"
    assert real.injector_flow_cc_min == 900.0 and real.catalog_injector_flow_cc_min == 2000.0
    assert real.map_sensor_kpa == (20.0, 300.0) and real.tank_fuel_id == "e27"
    plain = real_hardware(hw, spec)
    assert plain.tdc_offset_deg == 90.0 and plain.tank_fuel_id == "e100"


def test_checklist_variants(base_payload: Callable[..., dict[str, Any]]) -> None:
    hw = load_vehicle_hardware("classic-20t-swap")
    payload = base_payload()
    payload["trigger"] = {
        **payload["trigger"],
        "phase_sensor": "cam_hall",
        "injection_mode": "sequential",
    }
    base = BaseSetup.model_validate(payload)
    no_phase = hw.model_copy(update={"phase_sensor_present": False}) if hw else None
    items = {i.id: i for i in build_checklist(base, no_phase, n_cyl=6).items}
    assert items["trigger.phase"].status == "warning"
    assert items["trigger.firing_order"].status == "invalid"
    wb = build_checklist(
        BaseSetup.model_validate(
            {**base_payload(), "sensors": {"map": {"min_kpa": 20, "max_kpa": 400}}}
        ),
        hw,
    )
    wb_item = next(i for i in wb.items if i.id == "sensors.wideband")
    assert wb_item.status == "warning" and wb_item.code == "WIDEBAND_ABSENT"
    mismatch = build_checklist(
        BaseSetup.model_validate(base_payload()), hw, fuel_mismatch_suspected=True
    )
    fuel = next(i for i in mismatch.items if i.id == "fuel.type")
    assert fuel.code == "FUEL_MISMATCH_SUSPECTED" and mismatch.minimum_valid


async def test_repository_versions_and_override(api: Any) -> None:
    """T057/T058/T329: estado por sessão, versões imutáveis com ``setup_hash`` e override."""
    async with api.maker() as session:
        repo = ProfileRepository(session)
        state = EcuSessionState(
            session_id="s1", profile_id="ft-pro", ecu_state="awaiting_base_setup"
        )
        first = await repo.save_state(state, BaseSetup(), base_version=None)
        assert first is not None and first.version == 1 and len(first.setup_hash) == 64
        state = (await repo.get_state("s1")) or state
        assert state.latest_base_setup_version == 1
        with pytest.raises(SimRemapError) as exc:
            await repo.save_state(state, BaseSetup(), base_version=None)
        assert exc.value.error_code == "BASE_SETUP_VERSION_CONFLICT"
        second = await repo.save_state(state, BaseSetup(feature_package="race"), base_version=1)
        assert second is not None and second.version == 2
        assert (await repo.get_base("s1", 1)).base_setup == BaseSetup()  # type: ignore[union-attr]
        assert (await repo.get_base("s1")).version == 2  # type: ignore[union-attr]
        assert await repo.get_base("s9") is None
        assert await repo.count_base_versions("s1") == 2
        await repo.set_hardware_override("s1", "ft-pro", HardwareOverride(tdc_offset_shift_deg=3.0))
        got = await repo.get_state("s1")
        assert got is not None and got.hardware_override is not None
        assert got.hardware_override.tdc_offset_shift_deg == 3.0
        await repo.set_hardware_override("s1", "ft-pro", None)
        assert (await repo.get_state("s1")).hardware_override is None  # type: ignore[union-attr]
        await repo.set_hardware_override("s2", "oem-stage", HardwareOverride())
        assert (await repo.get_state("s2")).ecu_state == "oem"  # type: ignore[union-attr]
        assert await repo.get_state("nada") is None


def test_swap_plan_and_idempotency_ttl() -> None:
    plan = plan_swap(
        current_profile="ft-pro", target_profile="oem-stage", current_family="standalone",
        target_family="oem", confirm_snapshot=False, minimum_valid=False,
        stored_standalone_profile=None, swap_supported=False,
    )  # fmt: skip
    assert plan.ecu_state == "oem" and plan.map_action == "restore_snapshot"
    now = [datetime(2026, 10, 18, tzinfo=UTC)]
    idem = SwapIdempotency(clock=lambda: now[0])
    result = cast("SwapResult", object())
    idem.put("s", "r", result)
    idem.put("s", None, result)
    assert idem.get("s", "r") is result and idem.get("s", None) is None
    now[0] += timedelta(minutes=11)
    assert idem.get("s", "r") is None


async def test_invalid_registry_blocks_boot(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-01: descritor inválido no arranque ⇒ boot falha com ``PROFILE_REGISTRY_INVALID``."""

    def broken() -> Any:
        raise RegistryInvalid("NAV_TARGET_NOT_SUPPORTED", "teste")

    monkeypatch.setattr(router_mod, "get_registry", broken)
    with pytest.raises(BaseException):  # noqa: B017 - o lifespan propaga o erro
        async with LifespanManager(app, startup_timeout=30):
            pass
    assert registry_mod.get_registry() is not None
