"""Sessões com oficina de upgrades e flex fuel (002 RF-13 a RF-18, D-04; T042, T057).

REST (app real, catálogo real, banco SQLite e worker em processo):

- sem ``calibration_id`` a sessão nasce num clone da calibração de série (``source = user``,
  nome "Sessão <veículo> <perfil>");
- ``upgrades`` e ``ethanol_pct`` ecoados na resposta e logados em ``session.upgrades_applied``;
- turbo num motor sem turbo ⇒ 422 ``UPGRADE_NOT_COMPATIBLE``; flex num veículo sem E100 ⇒
  409 ``FUEL_NOT_ALLOWED``.

Laço real (``DynoSimTask`` com ``ProfiledEcu`` e a calibração ``oem-stage`` do catálogo),
regime permanente a plena carga:

- bicos de alta vazão ⇒ duty do bico menor; intercooler esportivo ⇒ IAT menor; downpipe ⇒
  EGT pré-turbina menor; forjados ⇒ limites estruturais maiores no dano;
- E85 no ``classic-20t-swap`` ⇒ λ medido na janela do alvo e sensor flex na telemetria;
- mesma seed, upgrades e etanol ⇒ telemetria idêntica.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import orjson
import pytest
from asgi_lifespan import LifespanManager

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dyno"))

from dyno_helpers import catalog_fuels, make_task, run_to_result

from simremap.catalog.contracts import VehicleSpec
from simremap.catalog.service import CatalogService
from simremap.catalog.upgrades import UpgradePackage, apply_upgrades
from simremap.damage.config import DamageConfig
from simremap.damage.mechanical import StructuralLimits
from simremap.dyno.runner import DynoSimTask
from simremap.ecu.calibration import compute_content_hash, parse_content
from simremap.physics.fuel_blend import blend_fuel

HOLD_S = 4.0


# --------------------------------------------------------------------------- REST


@pytest.fixture
async def real_client(settings_factory: Callable[..., Any]) -> AsyncIterator[httpx.AsyncClient]:
    from simremap.api.main import create_app

    app = create_app(settings_factory(worker_mode="process", log_level="INFO"))
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield client


async def _create(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/api/v1/sessions", json={"seed": 7, **body})


async def _close(client: httpx.AsyncClient, session_id: str) -> None:
    assert (await client.delete(f"/api/v1/sessions/{session_id}")).status_code == 204


async def test_rest_clone_upgrades_and_flex(
    real_client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
    log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
) -> None:
    client = real_client
    caplog.set_level("INFO")
    upgrades = {"injectors": "high_flow", "intercooler": "sport", "internals": "forged"}
    resp = await _create(client, vehicle_id="hatch-20t-gdi", upgrades=upgrades)
    assert resp.status_code == 201, resp.text
    session = resp.json()
    assert session["upgrades"] == {
        "turbo": "stock",
        "fuel_pump": "stock",
        "downpipe": "stock",
        **upgrades,
    }
    assert session["ethanol_pct"] is None and session["fuel_id"] == "e27"
    clone_id = session["calibration_id"]
    assert not clone_id.startswith("stock-")
    cal = (await client.get(f"/api/v1/calibrations/{clone_id}")).json()
    assert cal["metadata"]["source"] == "user"
    assert cal["metadata"]["name"].startswith("Sessão ") and "oem-stage" in cal["metadata"]["name"]
    applied = [e for e in log_events(caplog) if e.get("event") == "session.upgrades_applied"]
    assert applied and applied[-1]["upgrades"] == upgrades
    stored = (await client.get(f"/api/v1/sessions/{session['session_id']}")).json()
    assert stored["upgrades"] == session["upgrades"]
    await _close(client, session["session_id"])

    explicit = await _create(
        client, vehicle_id="hatch-20t-gdi", calibration_id="stock-hatch-20t-gdi-oem-stage"
    )
    assert explicit.status_code == 201, explicit.text
    assert explicit.json()["calibration_id"] == "stock-hatch-20t-gdi-oem-stage"
    await _close(client, explicit.json()["session_id"])

    no_e100 = await _create(client, vehicle_id="hatch-20t-gdi", ethanol_pct=85)
    assert no_e100.status_code == 409 and no_e100.json()["code"] == "FUEL_NOT_ALLOWED"
    turbo = await _create(client, vehicle_id="muscle-v8-sc", upgrades={"turbo": "upgraded"})
    assert turbo.status_code == 422, turbo.text
    problem = turbo.json()
    assert problem["code"] == "UPGRADE_NOT_COMPATIBLE"
    assert problem["category"] == "turbo" and problem["part_id"] == "upgraded"
    mixed = await _create(client, vehicle_id="classic-20t-swap", fuel_id="e27", ethanol_pct=85)
    assert mixed.status_code == 422 and mixed.json()["code"] == "VALIDATION_FAILED"

    flex = await _create(client, vehicle_id="classic-20t-swap", ethanol_pct=85)
    assert flex.status_code == 201, flex.text
    body = flex.json()
    assert body["fuel_id"] == "flex" and body["ethanol_pct"] == 85.0
    await _close(client, body["session_id"])
    closed = (await client.get(f"/api/v1/sessions/{body['session_id']}")).json()
    assert closed["state"] == "closed"
    assert closed["fuel_id"] == "flex" and closed["ethanol_pct"] == 85.0
    await asyncio.sleep(0)


# --------------------------------------------------------------------------- laço real


@cache
def _service() -> CatalogService:
    from simremap.catalog.service import load_catalog

    return load_catalog()


def _task(
    vehicle_id: str,
    pkg: UpgradePackage | None = None,
    ethanol_pct: float | None = None,
    seed: int = 42,
) -> DynoSimTask:
    """``DynoSimTask`` montado como o ``DynoService._create`` (upgrades e flex)."""
    service = _service()
    vehicle: VehicleSpec = service.get_vehicle(vehicle_id)
    upgraded = apply_upgrades(vehicle, pkg or UpgradePackage())
    fuels = catalog_fuels()
    stock_fuel = fuels[vehicle.stock_fuel_id]
    fuel = (
        stock_fuel if ethanol_pct is None else blend_fuel(fuels["e27"], fuels["e100"], ethanol_pct)
    )
    raw = service.get_factory_calibration_payload(vehicle_id, "oem-stage")
    content = parse_content({**raw, "vehicle_id": vehicle_id, "profile_id": "oem-stage"})
    return make_task(
        vehicle=upgraded.vehicle,
        fuel=fuel,
        stock_fuel=stock_fuel,
        calibration=content,
        calibration_id=f"stock-{vehicle_id}-oem-stage",
        calibration_hash=compute_content_hash(content),
        profile_hooks="registry",
        damage_config=DamageConfig(),
        seed=seed,
        exhaust_backpressure_scale=upgraded.physics.exhaust_backpressure_scale,
        fuel_pump_capacity_scale=upgraded.physics.fuel_pump_capacity_scale,
        ethanol_pct=ethanol_pct,
    )


def _hold(task: DynoSimTask, rpm: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Último frame com pedal a fundo de um ``steady_state_hold`` e todos os frames."""
    request = {
        "run_type": "steady_state_hold",
        "gear": 4,
        "cells": [{"rpm": rpm, "pedal_pct": 100.0, "hold_s": HOLD_S}],
    }
    outcome = run_to_result(task, request)
    assert outcome.run.state == "completed"
    frames = [e["payload"]["channels"] for e in outcome.of_type("telemetry.frame")]
    wot = [f for f in frames if (f.get("pedal_pct") or 0.0) >= 99.0]
    return wot[-1], frames


@cache
def _hatch_hold(category: str, part: str) -> dict[str, Any]:
    pkg = UpgradePackage.model_validate({category: part}) if category else UpgradePackage()
    return _hold(_task("hatch-20t-gdi", pkg), 4500.0)[0]


def test_high_flow_injectors_lower_duty() -> None:
    stock, big = _hatch_hold("", ""), _hatch_hold("injectors", "high_flow")
    assert big["injector_duty_pct"] < 0.8 * stock["injector_duty_pct"]
    assert big["lambda_measured"] == pytest.approx(stock["lambda_measured"], abs=0.02)


def test_sport_intercooler_lowers_iat() -> None:
    stock, sport = _hatch_hold("", ""), _hatch_hold("intercooler", "sport")
    assert sport["iat_c"] < stock["iat_c"] - 3.0


def test_downpipe_lowers_egt() -> None:
    stock, free = _hatch_hold("", ""), _hatch_hold("downpipe", "high_flow")
    assert free["egt_pre_turbo_c"] < stock["egt_pre_turbo_c"] - 10.0


def test_forged_internals_raise_damage_limits() -> None:
    stock = _task("hatch-20t-gdi")
    forged = _task("hatch-20t-gdi", UpgradePackage(internals="forged"))
    base = StructuralLimits.from_vehicle(stock.session.vehicle)
    strong = StructuralLimits.from_vehicle(forged.session.vehicle)
    assert strong.rod_force_limit_n == pytest.approx(1.35 * base.rod_force_limit_n)
    assert strong.cylinder_pressure_limit_kpa == pytest.approx(
        1.25 * base.cylinder_pressure_limit_kpa
    )
    assert strong.max_piston_temp_c == pytest.approx(base.max_piston_temp_c + 40.0)
    assert strong.rod_torque_limit_nm > base.rod_torque_limit_nm


def test_e85_lambda_in_window_and_sensor_published() -> None:
    frame, _ = _hold(_task("classic-20t-swap", ethanol_pct=85.0), 5000.0)
    assert frame["lambda_measured"] == pytest.approx(frame["lambda_target"], abs=0.03)
    assert frame["ethanol_pct"] == pytest.approx(85.0, abs=0.5)
    assert frame["cam_intake_deg"] == 0.0  # sem VVT no clássico


def test_vvt_channels_follow_targets() -> None:
    frame = _hatch_hold("", "")
    assert frame["cam_intake_target_deg"] > 0.0
    assert frame["cam_intake_deg"] == pytest.approx(frame["cam_intake_target_deg"], abs=0.5)
    assert frame["ethanol_pct"] is None


def test_same_seed_same_telemetry() -> None:
    pkg = UpgradePackage(turbo="upgraded", downpipe="high_flow", fuel_pump="high_flow")
    first = _hold(_task("classic-20t-swap", pkg, ethanol_pct=60.0, seed=9), 4500.0)[1]
    second = _hold(_task("classic-20t-swap", pkg, ethanol_pct=60.0, seed=9), 4500.0)[1]
    assert first == second and len(first) > 100


# --------------------------------------------------------------------------- sessão viva


def _install(task: DynoSimTask, pkg: UpgradePackage) -> dict[str, Any]:
    """``hardware.install`` como o ``DynoService.install_upgrades`` envia."""
    upgraded = apply_upgrades(_service().get_vehicle(task.session.vehicle.vehicle_id), pkg)
    task.handle_command(
        {
            "type": "hardware.install",
            "request_id": "hw1",
            "vehicle": upgraded.vehicle.model_dump(mode="json"),
            "exhaust_backpressure_scale": upgraded.physics.exhaust_backpressure_scale,
            "fuel_pump_capacity_scale": upgraded.physics.fuel_pump_capacity_scale,
        }
    )
    outputs = [orjson.loads(raw) for raw in task.drain_outputs()]
    acks: list[dict[str, Any]] = [o["payload"] for o in outputs if o["type"] == "ack"]
    assert len(acks) == 1
    return acks[0]


def test_live_install_keeps_session_clock_and_matches_new_session() -> None:
    task = _task("hatch-20t-gdi")
    stock = _hold(task, 4500.0)[0]
    tick = task.tick_index
    ack = _install(task, UpgradePackage(injectors="high_flow"))
    assert ack["ok"] is True and ack["health"]["engine_locked"] is False
    assert task.tick_index == tick
    assert task.session.physics.t_sim_s == pytest.approx(task.t_sim_s)
    live = _hold(task, 4500.0)[0]
    assert live["injector_duty_pct"] < 0.8 * stock["injector_duty_pct"]
    assert live["lambda_measured"] == pytest.approx(stock["lambda_measured"], abs=0.02)
    assert task.session.payload.vehicle.injectors.flow_cc_min == pytest.approx(
        1.5 * _service().get_vehicle("hatch-20t-gdi").injectors.flow_cc_min
    )


def test_live_install_refused_during_run() -> None:
    task = _task("hatch-20t-gdi")
    task.handle_command(
        {
            "type": "run.start",
            "run_id": "01JAB0000000000000000000AB",
            "request": {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000},
        }
    )
    task.drain_outputs()
    ack = _install(task, UpgradePackage(turbo="upgraded"))
    assert ack["ok"] is False and ack["code"] == "RUN_IN_PROGRESS"


async def test_rest_install_upgrades_on_live_session(
    real_client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
    log_events: Callable[[pytest.LogCaptureFixture], list[dict[str, Any]]],
) -> None:
    client = real_client
    caplog.set_level("INFO")
    created = await _create(client, vehicle_id="hatch-20t-gdi")
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]
    calibration_id = created.json()["active_calibration_id"]
    resp = await client.put(f"/api/v1/sessions/{sid}/upgrades", json={"turbo": "upgraded"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"] == sid and body["upgrades"]["turbo"] == "upgraded"
    assert body["active_calibration_id"] == calibration_id
    stored = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert stored["upgrades"]["turbo"] == "upgraded"
    installed = [e for e in log_events(caplog) if e.get("event") == "session.upgrades_installed"]
    assert installed and installed[-1]["upgrades"] == {"turbo": "upgraded"}
    back = await client.put(f"/api/v1/sessions/{sid}/upgrades", json={})
    assert back.status_code == 200 and back.json()["upgrades"]["turbo"] == "stock"
    await _close(client, sid)
    closed = await client.put(f"/api/v1/sessions/{sid}/upgrades", json={})
    assert closed.status_code == 409 and closed.json()["code"] == "SESSION_CLOSED"

    v8 = await _create(client, vehicle_id="muscle-v8-sc")
    assert v8.status_code == 201, v8.text
    v8_id = v8.json()["session_id"]
    bad = await client.put(f"/api/v1/sessions/{v8_id}/upgrades", json={"turbo": "upgraded"})
    assert bad.status_code == 422 and bad.json()["code"] == "UPGRADE_NOT_COMPATIBLE"
    await _close(client, v8_id)
