"""E-21 a E-25, ficha de instalação e integração com o ecu-core (T158; RF-01 a RF-04, RF-30)."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from simremap.profiles.registry import RegistryHooksProvider

CLASSIC = "classic-20t-swap"


async def test_list_profiles_e21(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ecu-profiles")
    assert resp.status_code == 200
    items = resp.json()
    assert [i["profile_id"] for i in items] == ["oem-stage", "ft-pro", "m1-race", "ht-elite"]
    assert items[0]["name"] == "OEM-Stage" and items[0]["family"] == "oem"
    assert set(items[0]) == {"profile_id", "name", "family", "inspiration", "descriptor_version"}


async def test_list_respects_feature_flag(app: FastAPI, client: httpx.AsyncClient) -> None:
    app.state.settings = app.state.settings.model_copy(
        update={"ecu_profiles_enabled": frozenset({"oem-stage", "ft-pro"})}
    )
    items = (await client.get("/api/v1/ecu-profiles")).json()
    assert [i["profile_id"] for i in items] == ["oem-stage", "ft-pro"]
    resp = await client.get("/api/v1/ecu-profiles/ht-elite")
    assert resp.status_code == 404 and resp.json()["code"] == "ECU_PROFILE_NOT_FOUND"


async def test_descriptor_e22(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ecu-profiles/ft-pro")
    assert resp.status_code == 200
    desc = resp.json()
    for key in (
        "navigation",
        "live_tunable_table_ids",
        "load_axis_channel",
        "accent_color",
        "tables",
        "strategies",
        "terminology",
        "display_units",
        "requires_base_setup",
        "base_setup_steps",
        "feature_packages",
    ):
        assert key in desc
    ve = next(t for t in desc["tables"] if t["kind"] == "ve")
    assert ve["default_x"]["values"][0] == 500.0 and ve["default_x"]["values"][-1] == 8000.0
    with_vehicle = (
        await client.get("/api/v1/ecu-profiles/ft-pro", params={"vehicle_id": CLASSIC})
    ).json()
    ve_v = next(t for t in with_vehicle["tables"] if t["kind"] == "ve")
    assert ve_v["default_x"]["values"][-1] == 7500.0
    base_pkg = (
        await client.get("/api/v1/ecu-profiles/m1-race", params={"feature_package": "base"})
    ).json()
    assert all(s["label"] != "Funções: competição" for s in base_pkg["navigation"])


async def test_descriptor_errors(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/ecu-profiles/xx-pro")
    assert resp.status_code == 404 and resp.json()["code"] == "ECU_PROFILE_NOT_FOUND"
    assert resp.headers["content-type"].startswith("application/problem+json")
    resp = await client.get("/api/v1/ecu-profiles/ft-pro", params={"vehicle_id": "nao-existe"})
    assert resp.status_code == 404 and resp.json()["code"] == "VEHICLE_NOT_FOUND"


async def test_descriptor_latency_g01(client: httpx.AsyncClient) -> None:
    """G-01 / RNF-02: ``GET /api/v1/ecu-profiles/{id}`` com p95 < 30 ms."""
    durations = []
    for k in range(40):
        pid = ["oem-stage", "ft-pro", "m1-race", "ht-elite"][k % 4]
        start = time.perf_counter()
        resp = await client.get(f"/api/v1/ecu-profiles/{pid}", params={"vehicle_id": CLASSIC})
        durations.append(time.perf_counter() - start)
        assert resp.status_code == 200
    p95 = statistics.quantiles(durations, n=20)[-1]
    assert p95 < 0.030


async def test_hooks_provider_installed_and_used_by_ecu_core(
    app: FastAPI, client: httpx.AsyncClient, oem_payload: Callable[..., dict[str, Any]]
) -> None:
    """RF-04 via E-16: ``oem-stage`` com two-step ⇒ 422 ``STRATEGY_NOT_SUPPORTED_BY_PROFILE``."""
    assert isinstance(app.state.ecu_profile_hooks, RegistryHooksProvider)
    payload = oem_payload(CLASSIC)
    body = {
        "vehicle_id": CLASSIC,
        "profile_id": "oem-stage",
        "source": "payload",
        "metadata": {"name": "Stage 1"},
        "tables": payload["tables"],
        "strategies": {**payload["strategies"], "two_step": {"kind": "two_step"}},
        "profile_params": payload["profile_params"],
        "fuel_model": payload["fuel_model"],
    }
    resp = await client.post("/api/v1/calibrations", json=body)
    assert resp.status_code == 422 and resp.json()["code"] == "STRATEGY_NOT_SUPPORTED_BY_PROFILE"
    body["strategies"] = payload["strategies"]
    resp = await client.post("/api/v1/calibrations", json=body)
    assert resp.status_code == 201, resp.text
    body["profile_id"] = "ft-pro"
    resp = await client.post("/api/v1/calibrations", json=body)
    assert resp.status_code == 422 and resp.json()["code"] == "TABLE_NOT_SUPPORTED_BY_PROFILE"


async def test_base_setup_get_awaiting_e24(api: Any) -> None:
    """RF-30: em ``awaiting_base_setup`` vêm checklist, ficha e ``base_setup = null``."""
    api.port.add(CLASSIC)
    await api.client.post(
        api.url("swap"), json={"target_profile_id": "ft-pro", "confirm_snapshot": True}
    )
    resp = await api.client.get(api.url("base-setup"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["base_setup"] is None and data["ecu_state"] == "awaiting_base_setup"
    assert data["checklist"]["minimum_valid"] is False and data["editable"] is True
    sheet = data["hardware_sheet"]
    assert sheet == {
        "trigger_wheel": "60-2",
        "phase_sensor_present": True,
        "firing_order": [1, 3, 4, 2],
        "injector_label_cc_min": 2000.0,
        "tank_fuel_id": "e100",
        "map_sensor_label_kpa": [20.0, 400.0],
        "tdc_offset_nominal_deg": 90.0,
        "n_cyl": 4,
        "displacement_cc": 1984.0,
    }
    assert not any("true" in key for key in sheet)


async def test_base_setup_oem_fixed_rf13(api: Any) -> None:
    """RF-13: no OEM a base é a de série, ``editable = false``."""
    api.port.add("hatch-20t-gdi")
    resp = await api.client.get(api.url("base-setup"))
    data = resp.json()
    assert data["editable"] is False and data["ecu_state"] == "oem"
    assert data["base_setup"]["trigger"]["wheel"] == "60-2"
    assert data["checklist"]["minimum_valid"] is True and data["base_setup_version"] is None
    resp = await api.client.put(
        api.url("base-setup"), json={"base_version": None, "base_setup": data["base_setup"]}
    )
    assert resp.status_code == 409 and resp.json()["code"] == "BASE_SETUP_NOT_EDITABLE_OEM"


async def test_base_setup_unknown_session(api: Any) -> None:
    resp = await api.client.get(api.url("base-setup", "ffffffffffffffffffffffffffffffff"))
    assert resp.status_code == 404 and resp.json()["code"] == "SESSION_NOT_FOUND"


async def test_no_port_means_no_sessions(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/sessions/0f5e9c2a6c1f4a7e9d2b4c3a9f102b3c/ecu/base-setup")
    assert resp.status_code == 404 and resp.json()["code"] == "SESSION_NOT_FOUND"


async def test_openapi_documents_codes(app: FastAPI, client: httpx.AsyncClient) -> None:
    schema = app.openapi()
    path = schema["paths"]["/api/v1/sessions/{session_id}/ecu/swap"]["post"]
    assert "SWAP_CONFIRMATION_REQUIRED" in path["x-error-codes"]
    assert "/api/v1/ecu-profiles/{profile_id}" in schema["paths"]
    assert "/api/v1/sessions/{session_id}/ecu/base-setup" in schema["paths"]


@pytest.mark.parametrize("vehicle_id", ["coupe-30t-i6", "muscle-v8-sc"])
async def test_other_vehicles_swap(api: Any, vehicle_id: str) -> None:
    api.port.add(vehicle_id)
    resp = await api.client.post(
        api.url("swap"), json={"target_profile_id": "ht-elite", "confirm_snapshot": True}
    )
    assert resp.status_code == 200, resp.text
    # a calibração de série do catálogo (knock_threshold 0–1) é materializada no arranque
    snapshot = resp.json()["oem_snapshot"]
    assert snapshot is not None and snapshot["calibration_id"] == f"stock-{vehicle_id}-oem-stage"
