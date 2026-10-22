"""Jornada do Rodrigo por REST com o laço real (ecu-profiles RF-31 e Apêndice F; T160).

App completa (catálogo real, banco, worker ``process``, ``ProfiledEcu`` e ``DamageConfig``
padrão), ``classic-20t-swap`` com E100 e ``seed`` 42:

1. Sessão em ``oem-stage`` (``ecu_state = oem``).
2. Swap para ``ft-pro`` ⇒ ``awaiting_base_setup`` com os 6 itens obrigatórios em falta e
   ``POST .../runs`` ⇒ 409 ``ECU_SETUP_INCOMPLETE``.
3. Base pela ficha (60-2, 1-3-4-2, bico 2000 cc/min da ficha, E100, MAP 20–400, wideband
   padrão) com mapa base do assistente ⇒ ``standalone_ready`` e calibração aplicada.
4. Puxada base no mapa do assistente sem falha.
5. Afinação de plena carga (λ medido → ``inj_base_ms``; avanço de MBT sem knock severo nas
   células com pressão), two-step a 4000 rpm e boost por marcha (2.ª marcha com teto)
   gravados no ecu-core e
   aplicados à sessão; o two-step é verificado no laço física + ``ProfiledEcu`` com a
   embraiagem premida (o rolo não tem entrada de arranque): média 4000 ± 100 rpm em
   blocos de 50 ms entre 0,8 e 2,3 s.
6. ``multi_pull`` de 3 puxadas: dispersão do pico ≤ 2 %, 0 ``FailureEvent`` e ≥ 300 whp.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.api.main import create_app
from simremap.catalog.service import load_catalog
from simremap.dyno.contracts import AmbientConditions, DynoLoad
from simremap.ecu.calibration import parse_content
from simremap.physics.contracts import PhysicsConfig
from simremap.physics.engine import PhysicsEngine
from simremap.profiles.adapter import build_profiled_ecu
from simremap.profiles.contracts import BaseSetup

CLASSIC = "classic-20t-swap"
TERMINAL = {"completed", "aborted", "engine_failed"}
TWO_STEP_RPM = 4000.0
GEAR2_CEILING_KPA = 180.0
WOT_MAP_KPA = 290.0  # pressão máxima do assistente (MAP de plena carga do clássico)
# Janela de retenção do arranque (s desde a embraiagem): a partir de ~2,5 s o retardo do
# two-step leva a EGT ao failsafe egt_high, que passa a arbitrar (arranque real ≈ 2 s)
HOLD_WINDOW_S = (0.8, 2.3)
REQUIRED = {
    "trigger.wheel",
    "injectors.flow",
    "injectors.dead_time",
    "fuel.type",
    "sensors.map",
    "base_map",
}


def rodrigo_base() -> dict[str, Any]:
    """Base do Rodrigo pela ficha do ``classic-20t-swap`` (Apêndice F, passo 3)."""
    return {
        "trigger": {"wheel": "60-2", "tdc_offset_deg": 90.0, "firing_order": [1, 3, 4, 2]},
        "injectors": {
            "flow_cc_min": 2000.0,
            "dead_time_v": [8.0, 10.0, 12.0, 14.0, 16.0],
            "dead_time_ms": [1.6, 1.2, 0.95, 0.8, 0.7],
        },
        "fuel": {"fuel_id": "e100", "afr_stoich": 9.0, "density_g_cc": 0.789},
        "sensors": {"map": {"min_kpa": 20.0, "max_kpa": 400.0}, "wideband": {}},
        "protection": {
            "rev_limit_rpm": 7200.0,
            "overspeed_rpm": 7500.0,
            "overboost_kpa": 300.0,
            "egt_max_c": 950.0,
        },
    }


@pytest.fixture
async def rodrigo_client(
    settings_factory: Callable[..., Any],
) -> AsyncIterator[tuple[httpx.AsyncClient, FastAPI]]:
    app: FastAPI = create_app(settings_factory(worker_mode="process"))
    app.state.dyno_task_options = {"steps_per_tick": 10}
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=120.0
        ) as client:
            yield client, app


async def wait_terminal(
    client: httpx.AsyncClient, run_id: str, timeout_s: float = 300.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        body: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if body["state"] in TERMINAL:
            return body
        await asyncio.sleep(0.2)
    raise AssertionError("a puxada não terminou")


async def start_run(client: httpx.AsyncClient, sid: str, request: dict[str, Any]) -> dict[str, Any]:
    resp = await client.post(f"/api/v1/sessions/{sid}/runs", json=request)
    assert resp.status_code == 202, resp.text
    return await wait_terminal(client, resp.json()["run_id"])


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for (x0, y0), (x1, y1) in itertools.pairwise(zip(xs, ys, strict=True)):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]  # pragma: no cover


def tune_wot(calibration: dict[str, Any], curve: list[dict[str, Any]]) -> dict[str, Any]:
    """Passos 5–6 do Apêndice F nas células com pressão (MAP ≥ 150 kPa).

    - Combustível: ``inj_base_ms`` × ``λ_medido / λ_alvo`` com o λ da puxada base por RPM.
    - Wastegate: base de duty por RPM × alvo de boost (cópia da série).
    - Ignição: o avanço de MBT sem knock severo encontrado na varredura célula a célula é o do
      schedule de referência do veículo (θ_pmax 16,5–18° ATDC), ancorado no MAP de plena
      carga do schedule e −0,08 °/kPa acima dele.
    """
    tables: dict[str, Any] = copy.deepcopy(calibration["tables"])
    catalog = load_catalog()
    # o assistente não gera a base do duty da wastegate (só o PID a 20 kPa do alvo atua e o
    # turbo fica na mola): o tuner copia a base de duty da calibração de série do veículo
    stock = catalog.get_factory_calibration_payload(CLASSIC, "oem-stage")
    assert stock is not None
    tables["boost_duty_base"] = copy.deepcopy(stock["tables"]["boost_duty_base"])
    schedule = catalog.get_reference_command_schedule(CLASSIC).points
    s_rpm = [p.rpm for p in schedule]
    s_adv = [p.ignition_advance_deg for p in schedule]
    s_map = [p.map_target_kpa for p in schedule]
    c_rpm = [p["rpm"] for p in curve]
    c_lam = [p["lambda"] for p in curve]
    lam_t = tables["lambda_target"]
    for name in ("inj_base_ms", "ignition_base"):
        table = tables[name]
        xs, ys = table["x"]["values"], table["y"]["values"]
        for j, map_kpa in enumerate(ys):
            if map_kpa < 150.0:
                continue
            for i, rpm in enumerate(xs):
                if name == "inj_base_ms":
                    if not c_rpm[0] <= rpm <= c_rpm[-1]:
                        continue
                    target = lam_t["values"][j][i]
                    table["values"][j][i] *= _interp(c_rpm, c_lam, rpm) / target
                else:
                    adv = _interp(s_rpm, s_adv, rpm) - 0.08 * (map_kpa - _interp(s_rpm, s_map, rpm))
                    table["values"][j][i] = round(min(max(adv, 5.0), 35.0), 2)
    return tables


def launch_and_gear_calibration(calibration: dict[str, Any]) -> dict[str, Any]:
    """Two-step a 4000 rpm (embraiagem) e boost por marcha com teto na 2.ª marcha."""
    strategies = copy.deepcopy(calibration["strategies"])
    strategies["two_step"] = {
        **strategies.get("two_step", {"kind": "two_step"}),
        "enabled": True,
        "target_rpm": TWO_STEP_RPM,
        "activation": "clutch",
    }
    strategies["boost_control"] = {**strategies["boost_control"], "by_gear_enabled": True}
    tables = copy.deepcopy(calibration["tables"])
    tables["boost_target_gear"] = {
        "table_id": "boost_target_gear",
        "kind": "boost_target_gear",
        "unit": "kPa",
        "live_tunable": True,
        "description": "Teto de boost por marcha",
        "decimals": 0,
        "dims": 2,
        "x": {"quantity": "gear", "values": [1.0, 2.0, 3.0, 4.0, 5.0]},
        "values": [150.0, GEAR2_CEILING_KPA, 400.0, 400.0, 400.0],
    }
    for table in tables.values():
        for key in ("min", "max"):
            table.pop(key, None)
        for axis in ("x", "y"):
            if isinstance(table.get(axis), dict):
                table[axis] = {k: v for k, v in table[axis].items() if k in ("quantity", "values")}
    metadata = {
        k: v
        for k, v in calibration["metadata"].items()
        if k in ("name", "author_nickname", "notes", "source", "extra")
    }
    metadata["change_summary"] = "two-step 4000 rpm e boost por marcha"
    return {
        "fuel_model": calibration["fuel_model"],
        "tables": tables,
        "strategies": strategies,
        "profile_params": calibration.get("profile_params", {}),
        "metadata": metadata,
    }


def _profiled_ecu(content_json: dict[str, Any]) -> Any:
    catalog = load_catalog()
    vehicle = catalog.get_vehicle(CLASSIC)
    content = parse_content({**content_json, "vehicle_id": CLASSIC, "profile_id": "ft-pro"})
    return build_profiled_ecu(
        vehicle=vehicle,
        stock_fuel=catalog.get_fuel(vehicle.stock_fuel_id),
        profile_id="ft-pro",
        ecu_state="standalone_ready",
        base_setup=BaseSetup.model_validate(rodrigo_base()),
        calibration=content,
    )


def boost_target_by_gear(content_json: dict[str, Any]) -> dict[int, float]:
    """``EcuStatus.boost_target_kpa`` a 5000 rpm e borboleta 100 % em cada marcha."""
    catalog = load_catalog()
    vehicle = catalog.get_vehicle(CLASSIC)
    physics = PhysicsEngine(
        PhysicsConfig(sim_hz=1000), vehicle, catalog.get_fuel("e100"), initial_ect_c=90.0
    )
    physics.crank(5000.0)
    out: dict[int, float] = {}
    for gear in (2, 4):
        ecu = _profiled_ecu(content_json)
        sensors = physics.read_sensors().model_copy(
            update={"gear": gear, "tps_pct": 100.0, "pedal_pct": 100.0}
        )
        out[gear] = float(ecu.step(sensors, 0.001).status.boost_target_kpa)
    return out


def two_step_hold_rpm(content_json: dict[str, Any]) -> list[float]:
    """Laço física + ``ProfiledEcu`` com embraiagem premida e pedal 100 %.

    Devolve a rotação média de cada bloco de 50 ms dentro da janela.
    """
    catalog = load_catalog()
    vehicle = catalog.get_vehicle(CLASSIC)
    ecu = _profiled_ecu(content_json)
    physics = PhysicsEngine(
        PhysicsConfig(sim_hz=1000), vehicle, catalog.get_fuel("e100"), initial_ect_c=90.0
    )
    physics.crank(1500.0)
    dt = 0.001
    rpms: list[float] = []
    for k in range(round(HOLD_WINDOW_S[1] / dt)):
        sensors = physics.read_sensors().model_copy(update={"pedal_pct": 100.0})
        result = ecu.step(sensors, dt)
        load = DynoLoad.model_construct(
            reflected_inertia_kg_m2=0.0,
            load_torque_crank_nm=0.0,
            gear=0,
            wheel_to_crank_ratio=0.0,
            pedal_pct=100.0,
            fan_air_speed_m_s=15.0,
            ambient=AmbientConditions(),
            vehicle_speed_kmh=0.0,
            clutch_pressed=True,
            launch_switch=False,
            shift_request=False,
            antilag_switch=False,
        )
        state = physics.step(result.commands, load, dt)
        if HOLD_WINDOW_S[0] <= k * dt < HOLD_WINDOW_S[1]:
            rpms.append(state.rpm)
    # rotação média por bloco de 50 ms (≈ 1,7 ciclo a 4000 rpm, como um conta-giros)
    return [sum(rpms[i : i + 50]) / 50.0 for i in range(0, len(rpms) - 49, 50)]


async def test_rodrigo_swap_setup_launch_and_repeatable_pulls(
    rodrigo_client: tuple[httpx.AsyncClient, FastAPI],
) -> None:
    client, _app = rodrigo_client
    # 1. Sessão de série.
    resp = await client.post("/api/v1/sessions", json={"vehicle_id": CLASSIC, "seed": 42})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["session_id"]
    assert resp.json()["ecu_state"] == "oem"

    # 2. Swap para ft-pro.
    resp = await client.post(
        f"/api/v1/sessions/{sid}/ecu/swap",
        json={"target_profile_id": "ft-pro", "confirm_snapshot": True},
    )
    assert resp.status_code == 200, resp.text
    swap = resp.json()
    assert swap["ecu_state"] == "awaiting_base_setup"
    missing = {i["id"] for i in swap["checklist"]["items"] if i["status"] == "missing"}
    assert REQUIRED <= missing
    blocked = await client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "baseline_pull"})
    assert blocked.status_code == 409 and blocked.json()["code"] == "ECU_SETUP_INCOMPLETE"

    # 3. Base pela ficha com mapa base do assistente.
    resp = await client.put(
        f"/api/v1/sessions/{sid}/ecu/base-setup",
        json={
            "base_version": None,
            "base_setup": rodrigo_base(),
            "generate_base_map": True,
            "wizard": {"max_map_kpa": WOT_MAP_KPA},
        },
    )
    assert resp.status_code == 200, resp.text
    setup = resp.json()
    assert setup["ecu_state"] == "standalone_ready" and setup["calibration_id"]
    session = (await client.get(f"/api/v1/sessions/{sid}")).json()
    assert session["profile_id"] == "ft-pro" and session["ecu_state"] == "standalone_ready"

    # 4. Puxada base no mapa do assistente.
    base_run = await start_run(client, sid, {"run_type": "baseline_pull"})
    assert base_run["state"] == "completed", base_run.get("abort_reason")
    assert base_run["summary"]["failure_event_id"] is None

    # 5. Afinação de plena carga, two-step e boost por marcha no ecu-core, aplicados à sessão.
    cal_id = setup["calibration_id"]
    current = (await client.get(f"/api/v1/calibrations/{cal_id}")).json()
    curve = (await client.get(f"/api/v1/runs/{base_run['run_id']}")).json()["curve"]
    current["tables"] = tune_wot(current, curve)
    update = launch_and_gear_calibration(current)
    resp = await client.put(
        f"/api/v1/calibrations/{cal_id}",
        json={"base_version": current["version"], **update},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/sessions/{sid}/calibration", json={"calibration_id": cal_id})
    assert resp.status_code == 200, resp.text
    tuned = (await client.get(f"/api/v1/calibrations/{cal_id}")).json()
    blocks = two_step_hold_rpm({k: tuned[k] for k in ("fuel_model", "tables", "strategies")})
    # média ± 100 rpm; corte de faísca com o motor desacoplado (inércia só do motor): ≥ 80 %
    # dos blocos de 50 ms dentro de ± 100 rpm e todos dentro de ± 150 rpm
    inside = [b for b in blocks if abs(b - TWO_STEP_RPM) <= 100.0]
    assert abs(sum(blocks) / len(blocks) - TWO_STEP_RPM) <= 100.0
    assert len(inside) >= 0.8 * len(blocks)
    assert all(abs(b - TWO_STEP_RPM) <= 150.0 for b in blocks)
    targets = boost_target_by_gear({k: tuned[k] for k in ("fuel_model", "tables", "strategies")})
    assert targets[2] <= GEAR2_CEILING_KPA + 1e-6 < WOT_MAP_KPA - 1e-6 <= targets[4]

    # 6. Puxadas repetidas sem falha.
    multi = await start_run(client, sid, {"run_type": "multi_pull"})
    assert multi["state"] == "completed", multi.get("abort_reason")
    assert len(multi["pulls"]) == 3
    assert multi["repeatability"]["peak_whp_spread_pct"] <= 2.0
    assert multi["summary"]["failure_event_id"] is None
    assert multi["summary"]["peak_whp"] >= 300.0
    health = (await client.get(f"/api/v1/sessions/{sid}/engine/health")).json()
    assert health["engine_locked"] is False and not health["failures"]
