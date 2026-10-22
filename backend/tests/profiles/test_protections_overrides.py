"""Proteções da ``BaseSetup`` em estratégias e ``HardwareOverride`` (T157; RF-14, RF-27, RF-29)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.ecu.contracts import BoostControlConfig, FailsafeConfig, RevLimiterConfig
from simremap.physics.contracts import SensorReadings
from simremap.profiles.contracts import HardwareOverride, ProtectionLimits
from simremap.profiles.hooks.standalone import failsafe_rules, protection_strategies
from simremap.profiles.repository import ProfileRepository
from simremap.profiles.worker import handle_apply_command, handle_swap_command

CLASSIC = "classic-20t-swap"
SensorFactory = Callable[..., SensorReadings]


def test_protection_strategies_rf27() -> None:
    """EGT 900 °C, corte 7200 rpm e overboost 260 kPa ⇒ failsafe, limitador e overboost."""
    limits = ProtectionLimits(
        rev_limit_rpm=7200.0, overspeed_rpm=7500.0, overboost_kpa=260.0, egt_max_c=900.0,
        ect_max_c=105.0, oil_pressure_min_kpa=150.0, lean_delta_lambda=0.08,
    )  # fmt: skip
    out = protection_strategies(limits, wideband=True)
    fs = out["failsafe"]
    assert isinstance(fs, FailsafeConfig)
    rules = {r.rule_id: r for r in fs.rules}
    assert rules["egt_high"].threshold == 900.0
    assert rules["ect_high"].threshold == 105.0
    assert rules["oil_pressure_low"].threshold == 150.0
    assert rules["lean_under_load"].threshold == pytest.approx(0.08)
    assert fs.overspeed_rpm == 7500.0
    rl = out["rev_limiter"]
    assert isinstance(rl, RevLimiterConfig) and rl.hard_rpm == 7200.0
    bc = out["boost_control"]
    assert isinstance(bc, BoostControlConfig) and bc.overboost_kpa == 260.0
    assert out["closed_loop"].enabled is True
    assert protection_strategies(limits, wideband=False)["closed_loop"].enabled is False
    # Opções do usuário preservadas; só os campos da base mudam.
    existing = {
        "boost_control": BoostControlConfig(kp_pct_per_kpa=1.5, by_gear_enabled=True),
        "rev_limiter": RevLimiterConfig(
            hard_rpm=9000.0, soft_window_rpm=800.0, cut_mode="spark_cut"
        ),
    }
    low = ProtectionLimits(rev_limit_rpm=2000.0, overspeed_rpm=2500.0)
    kept = protection_strategies(low, wideband=True, existing=existing)  # type: ignore[arg-type]
    assert kept["boost_control"].kp_pct_per_kpa == 1.5  # type: ignore[union-attr]
    assert kept["boost_control"].by_gear_enabled is True  # type: ignore[union-attr]
    assert kept["rev_limiter"].cut_mode == "spark_cut"  # type: ignore[union-attr]
    assert kept["rev_limiter"].hard_rpm == 2000.0  # type: ignore[union-attr]
    assert len(failsafe_rules(low)) == 7


async def test_limits_only_change_creates_one_version(
    api: Any, base_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-27: só os limites mudam ⇒ 1 versão com ``change_summary`` "base-setup vN: limites"."""
    api.port.add(CLASSIC)
    await api.client.post(
        api.url("swap"), json={"target_profile_id": "ft-pro", "confirm_snapshot": True}
    )
    first = (
        await api.client.put(
            api.url("base-setup"),
            json={"base_version": None, "base_setup": base_payload(), "generate_base_map": True},
        )
    ).json()
    cal_id = first["calibration_id"]
    payload = base_payload()
    payload["protection"]["egt_max_c"] = 880.0
    resp = await api.client.put(
        api.url("base-setup"), json={"base_version": 1, "base_setup": payload}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["calibration_id"] == cal_id and data["calibration_version"] == 2
    assert data["ecu_state"] == "standalone_ready" and data["base_setup_version"] == 2
    cal = (await api.client.get(f"/api/v1/calibrations/{cal_id}")).json()
    assert cal["metadata"]["change_summary"] == "base-setup v2: limites"
    egt = next(r for r in cal["strategies"]["failsafe"]["rules"] if r["rule_id"] == "egt_high")
    assert egt["threshold"] == 880.0
    # Mesmos limites: nenhuma versão nova da calibração.
    same = (
        await api.client.put(api.url("base-setup"), json={"base_version": 2, "base_setup": payload})
    ).json()
    assert same["calibration_version"] == 2 and same["base_setup_version"] == 3
    # Limites novos sem aplicar à calibração.
    payload["protection"]["egt_max_c"] = 870.0
    skip = (
        await api.client.put(
            api.url("base-setup"),
            json={"base_version": 3, "base_setup": payload, "apply_limits_to_calibration": False},
        )
    ).json()
    assert skip["calibration_version"] == 2
    # RF-14: troca do modo de injeção gera uma versão nova com inj_base_ms derivado do VE.
    mode = (
        await api.client.put(
            api.url("base-setup"),
            json={
                "base_version": 4,
                "base_setup": payload,
                "wizard": {"fuel_model_mode": "speed_density_ve"},
                "apply_limits_to_calibration": False,
            },
        )
    ).json()
    assert mode["calibration_version"] == 3
    cal3 = (await api.client.get(f"/api/v1/calibrations/{cal_id}")).json()
    assert cal3["fuel_model"]["mode"] == "speed_density_ve"
    assert cal3["metadata"]["change_summary"] == "base-setup v5: modo speed_density_ve"


async def test_hardware_override_hidden_and_applied(
    api: Any,
    base_payload: Callable[..., dict[str, Any]],
    vehicle: Callable[[str], VehicleSpec],
    catalog: CatalogService,
    sensors: SensorFactory,
) -> None:
    """RF-29: PMS deslocado 8° produz o S-01 sem diferença visível na base nem na ficha."""
    sid = api.port.add(CLASSIC)
    async with api.maker() as session:
        await ProfileRepository(session).set_hardware_override(
            sid, "oem-stage", HardwareOverride(tdc_offset_shift_deg=8.0)
        )
    await api.client.post(
        api.url("swap"), json={"target_profile_id": "ft-pro", "confirm_snapshot": True}
    )
    resp = await api.client.put(
        api.url("base-setup"),
        json={"base_version": None, "base_setup": base_payload(), "generate_base_map": True},
    )
    data = resp.json()
    assert data["hardware_sheet"]["tdc_offset_nominal_deg"] == 90.0
    assert "hardware_override" not in json.dumps(data)
    assert data["base_setup"]["trigger"]["tdc_offset_deg"] == 90.0
    got = await api.client.get(api.url("base-setup"))
    assert "tdc_offset_shift" not in got.text and "tdc_offset_true" not in got.text
    cmd = api.port.commands[-1]
    assert cmd.hardware_override_json is not None
    classic = vehicle(CLASSIC)
    ecu, ack = handle_swap_command(
        cmd.to_command(), vehicle=classic, stock_fuel=catalog.get_fuel("e100")
    )
    assert ack["type"] == "ack" and ack["ecu_state"] == "standalone_ready"
    res = ecu.step(sensors(), 0.001)
    for cmd_adv, real in zip(
        res.status.ignition_advance_deg, res.commands.ignition_advance_deg, strict=True
    ):
        assert real == pytest.approx(cmd_adv + 8.0, abs=0.01)
    # calibration.apply pelo runtime do perfil
    apply_cmd = {
        "type": "calibration.apply",
        "request_id": "r1",
        "calibration_id": cmd.calibration_id,
        "version": 1,
        "content_hash": cmd.content_hash,
        "mode": "full",
        "payload_json": cmd.calibration_payload_json,
    }
    assert handle_apply_command(ecu, apply_cmd)["type"] == "ack"
    with pytest.raises(ValueError):
        handle_swap_command({"type": "x"}, vehicle=classic, stock_fuel=catalog.get_fuel("e100"))
    with pytest.raises(ValueError):
        handle_swap_command(
            {"type": "ecu.swap", "ecu_state": "zz"},
            vehicle=classic,
            stock_fuel=catalog.get_fuel("e100"),
        )
    empty, _ = handle_swap_command(
        {"type": "ecu.swap", "ecu_state": "awaiting_base_setup", "profile_id": "ft-pro"},
        vehicle=classic,
        stock_fuel=catalog.get_fuel("e100"),
    )
    with pytest.raises(ValueError):
        handle_apply_command(empty, apply_cmd)
