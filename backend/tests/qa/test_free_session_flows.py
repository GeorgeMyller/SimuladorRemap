"""QA da sessão livre pela API real (003 T020; RF-12 a RF-14). Marcador ``e2e``:
``uv run --frozen pytest -m e2e tests/qa/test_free_session_flows.py``.

App de produção em worker ``process``:

- sessão sem calibração ⇒ clone do usuário; encerrar ⇒ ``closed``; retomar = nova sessão
  com a mesma calibração (não há rota de reabertura);
- Stage Builder: cada peça e o pacote completo em cada veículo; turbo no V8 sem turbo ⇒
  422 ``UPGRADE_NOT_COMPATIBLE``;
- etanol: E27/E50/E85/E100 no clássico ⇒ ``flex``; fora de 27–100 ⇒ 422; veículo sem
  E100 ⇒ 409 ``FUEL_NOT_ALLOWED``;
- os 4 tipos de puxada com resumos coerentes;
- quebra do motor ⇒ laudo forense ⇒ restauração ⇒ nova puxada;
- swap OEM → FT-Pro / M1-Race / HT-Elite e setup base;
- calibração aplicada à sessão e PATCH de tabela live-tunable durante a puxada.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Final

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_play import swap_and_setup
from qa_support import (
    API,
    Json,
    apply_calibration,
    close_session,
    create_session,
    get_calibration,
    map_cells,
    open_client,
    real_app,
    replace_calibration,
    run_pull,
    start_run,
    wait_run,
)

pytestmark = pytest.mark.e2e

HATCH: Final = "hatch-20t-gdi"
CLASSIC: Final = "classic-20t-swap"
MUSCLE: Final = "muscle-v8-sc"
VEHICLES: Final = (HATCH, "coupe-30t-i6", CLASSIC, MUSCLE)
PARTS: Final[dict[str, str]] = {
    "turbo": "upgraded",
    "injectors": "high_flow",
    "fuel_pump": "high_flow",
    "intercooler": "sport",
    "downpipe": "high_flow",
    "internals": "forged",
}
WITHOUT_TURBO: Final = frozenset({MUSCLE})
SPREAD_MAX_PCT: Final = 3.0
TORQUE_TABLES: Final = ("torque_request", "torque_limit", "torque_limit_gear")


@pytest.fixture
async def client(settings_factory: Callable[..., Any]) -> AsyncIterator[httpx.AsyncClient]:
    async with open_client(real_app(settings_factory(worker_mode="process"))) as c:
        yield c


async def _status(client: httpx.AsyncClient, **body: Any) -> tuple[int, Json]:
    resp = await client.post(f"{API}/sessions", json={"seed": 1, **body})
    data: Json = resp.json()
    if resp.status_code == 201:
        await close_session(client, data["session_id"])
    return resp.status_code, data


# --------------------------------------------------------------------------- sessão livre


async def test_free_session_close_and_resume(client: httpx.AsyncClient) -> None:
    session = await create_session(client, vehicle_id=HATCH)
    cal = await get_calibration(client, session["calibration_id"])
    assert cal["metadata"]["source"] == "user" and session["state"] == "ready"

    await close_session(client, session["session_id"])

    closed = (await client.get(f"{API}/sessions/{session['session_id']}")).json()
    assert closed["state"] == "closed"
    again = await client.delete(f"{API}/sessions/{session['session_id']}")
    assert again.status_code == 404
    resumed = await create_session(client, vehicle_id=HATCH, calibration_id=cal["calibration_id"])
    assert resumed["calibration_id"] == cal["calibration_id"]
    run = await run_pull(client, resumed["session_id"], run_type="baseline_pull")
    assert run["state"] == "completed" and run["calibration_hash"] == cal["content_hash"]
    await close_session(client, resumed["session_id"])


# --------------------------------------------------------------------------- Stage Builder


@pytest.mark.parametrize("vehicle_id", VEHICLES)
async def test_stage_builder_parts(client: httpx.AsyncClient, vehicle_id: str) -> None:
    for category, part in PARTS.items():
        status, body = await _status(client, vehicle_id=vehicle_id, upgrades={category: part})
        if category == "turbo" and vehicle_id in WITHOUT_TURBO:
            assert (status, body["code"]) == (422, "UPGRADE_NOT_COMPATIBLE")
            assert (body["category"], body["part_id"]) == (category, part)
            continue
        assert status == 201, body
        assert body["upgrades"][category] == part

    status, body = await _status(client, vehicle_id=vehicle_id, upgrades=PARTS)

    if vehicle_id in WITHOUT_TURBO:
        assert (status, body["code"]) == (422, "UPGRADE_NOT_COMPATIBLE")
    else:
        assert status == 201 and body["upgrades"] == PARTS


# --------------------------------------------------------------------------- etanol


@pytest.mark.parametrize("ethanol_pct", [27, 50, 85, 100])
async def test_flex_blends_on_classic(client: httpx.AsyncClient, ethanol_pct: int) -> None:
    session = await create_session(client, vehicle_id=CLASSIC, ethanol_pct=ethanol_pct)

    run = await run_pull(client, session["session_id"], run_type="baseline_pull")

    assert (session["fuel_id"], session["ethanol_pct"]) == ("flex", float(ethanol_pct))
    assert run["state"] == "completed", run.get("abort_reason")
    await close_session(client, session["session_id"])


@pytest.mark.parametrize("ethanol_pct", [26, 26.9, 101])
async def test_ethanol_out_of_range(client: httpx.AsyncClient, ethanol_pct: float) -> None:
    status, body = await _status(client, vehicle_id=CLASSIC, ethanol_pct=ethanol_pct)
    assert (status, body["code"]) == (422, "VALIDATION_FAILED")


@pytest.mark.parametrize("vehicle_id", [HATCH, "coupe-30t-i6", MUSCLE])
async def test_ethanol_needs_e100(client: httpx.AsyncClient, vehicle_id: str) -> None:
    status, body = await _status(client, vehicle_id=vehicle_id, ethanol_pct=85)
    assert (status, body["code"]) == (409, "FUEL_NOT_ALLOWED")


# --------------------------------------------------------------------------- puxadas


async def test_four_run_types_have_coherent_summaries(client: httpx.AsyncClient) -> None:
    sid = (await create_session(client, vehicle_id=HATCH))["session_id"]

    base = await run_pull(client, sid, run_type="baseline_pull")
    sweep = await run_pull(client, sid, start_rpm=2500, end_rpm=6000, ramp_rate_rpm_s=500)
    cells = [
        {"rpm": 3000, "pedal_pct": 50, "hold_s": 3},
        {"rpm": 4500, "pedal_pct": 100, "hold_s": 3},
        {"rpm": 2500, "map_kpa": 150, "hold_s": 3},
    ]
    hold = await run_pull(client, sid, run_type="steady_state_hold", cells=cells)
    multi = await run_pull(client, sid, run_type="multi_pull", pull_count=2, cooldown_s=10)

    for run in (base, sweep, hold, multi):
        assert run["state"] == "completed", (run["run_type"], run.get("abort_reason"))
        assert run["summary"]["peak_whp"] > 100.0
        assert run["summary"]["failure_event_id"] is None
        log = await client.get(f"{API}/runs/{run['run_id']}/log")
        assert log.status_code == 200, run["run_type"]
    rpms = [p["rpm"] for p in sweep["curve"]]
    assert 2400.0 <= min(rpms) and max(rpms) <= 6000.0 + 50.0
    assert sorted(p["cell_index"] for p in hold["curve"]) == [0, 1, 2]
    assert [p["pull_index"] for p in multi["pulls"]] == [1, 2]
    peaks = [p["summary"]["peak_whp"] for p in multi["pulls"]]
    assert multi["summary"]["peak_whp"] == pytest.approx(max(peaks))
    assert multi["repeatability"]["peak_whp_spread_pct"] <= SPREAD_MAX_PCT
    await close_session(client, sid)


# --------------------------------------------------------------------------- quebra


def _exaggerated(content: Json) -> None:
    tables = content["tables"]
    for name in TORQUE_TABLES:
        table = tables[name]
        if table["dims"] == 3:
            map_cells(table, lambda _r, _k, v: 1.5 * v)
        else:
            table["values"] = [1.5 * v for v in table["values"]]
    map_cells(tables["oem_pressure_target"], lambda _r, _k, v: 280.0 if v >= 150.0 else v)
    map_cells(tables["ignition_base"], lambda _r, _k, v: v + 8.0)


async def test_engine_failure_forensics_and_restore(client: httpx.AsyncClient) -> None:
    session = await create_session(client, vehicle_id=HATCH)
    sid, cal_id = session["session_id"], session["calibration_id"]
    stock = await get_calibration(client, cal_id)
    await replace_calibration(client, cal_id, _exaggerated, "exagerada")
    await apply_calibration(client, sid, cal_id)

    failed = await run_pull(client, sid, ramp_rate_rpm_s=150.0)

    assert failed["state"] == "engine_failed"
    summary = failed["summary"]
    assert summary["failure_event_id"]
    assert summary["forensic_report_url"] == f"{API}/runs/{failed['run_id']}/forensic-report"
    health = (await client.get(f"{API}/sessions/{sid}/engine/health")).json()
    assert health["engine_locked"] is True and health["failures"]
    blocked = await client.post(f"{API}/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    assert (blocked.status_code, blocked.json()["code"]) == (409, "ENGINE_DESTROYED")
    report = (await client.get(summary["forensic_report_url"])).json()
    assert report["report_kind"] == "failure"
    assert report["failure_event"]["failure_event_id"] == summary["failure_event_id"]
    assert len(report["causal_chain"]) >= 3 and report["recommendations"]

    restored = await client.post(f"{API}/sessions/{sid}/engine/restore", json={"note": "QA"})
    assert restored.status_code == 200, restored.text
    assert restored.json()["engine_locked"] is False and restored.json()["restore_count"] == 1
    await replace_calibration(
        client, cal_id, lambda c: c.update({k: stock[k] for k in ("tables", "strategies")})
    )
    await apply_calibration(client, sid, cal_id)
    after = await run_pull(client, sid)
    assert after["state"] == "completed", after.get("abort_reason")
    await close_session(client, sid)


# --------------------------------------------------------------------------- ECU


@pytest.mark.parametrize("profile_id", ["ft-pro", "m1-race", "ht-elite"])
async def test_swap_and_base_setup(client: httpx.AsyncClient, profile_id: str) -> None:
    sid = (await create_session(client, vehicle_id=CLASSIC, fuel_id="e100"))["session_id"]
    oem = (await client.get(f"{API}/sessions/{sid}/ecu/base-setup")).json()
    assert oem["editable"] is False and oem["ecu_state"] == "oem"
    swap = await client.post(
        f"{API}/sessions/{sid}/ecu/swap",
        json={"target_profile_id": profile_id, "confirm_snapshot": False},
    )
    assert (swap.status_code, swap.json()["code"]) == (422, "SWAP_CONFIRMATION_REQUIRED")

    setup = await swap_and_setup(client, sid, profile_id)

    view = (await client.get(f"{API}/sessions/{sid}/ecu/base-setup")).json()
    assert view["editable"] is True and view["base_setup_version"] == 1
    assert view["ecu_state"] == "standalone_ready"
    session = (await client.get(f"{API}/sessions/{sid}")).json()
    assert (session["profile_id"], session["ecu_state"]) == (profile_id, "standalone_ready")
    run = await run_pull(client, sid, run_type="baseline_pull")
    assert run["state"] == "completed", run.get("abort_reason")
    assert run["calibration_id"] == setup["calibration_id"]
    await close_session(client, sid)


async def test_swap_blocks_runs_until_base_setup(client: httpx.AsyncClient) -> None:
    sid = (await create_session(client, vehicle_id=CLASSIC, fuel_id="e100"))["session_id"]
    swap = await client.post(
        f"{API}/sessions/{sid}/ecu/swap",
        json={"target_profile_id": "ft-pro", "confirm_snapshot": True},
    )
    assert swap.status_code == 200, swap.text

    blocked = await client.post(f"{API}/sessions/{sid}/runs", json={"run_type": "baseline_pull"})

    assert (blocked.status_code, blocked.json()["code"]) == (409, "ECU_SETUP_INCOMPLETE")
    assert {"injectors.flow", "base_map"} <= set(blocked.json()["pending"])
    await close_session(client, sid)


async def _patch_ignition(client: httpx.AsyncClient, cal_id: str) -> None:
    cal = await get_calibration(client, cal_id)
    patch = await client.patch(
        f"{API}/calibrations/{cal_id}/tables/ignition_base",
        json={
            "base_version": cal["version"],
            "op": "add",
            "cells": [{"row": 0, "col": 0, "value": -1}],
        },
    )
    assert patch.status_code == 200, patch.text


async def _apply(client: httpx.AsyncClient, sid: str, cal_id: str) -> httpx.Response:
    return await client.post(
        f"{API}/sessions/{sid}/calibration",
        json={"calibration_id": cal_id, "profile_options": {"auto_fix_checksum": True}},
    )


def _overboost(content: Json) -> None:
    content["strategies"]["boost_control"]["overboost_kpa"] = 280.0


async def test_live_patch_during_pull(client: httpx.AsyncClient) -> None:
    session = await create_session(client, vehicle_id=HATCH)
    sid, cal_id = session["session_id"], session["calibration_id"]
    assert (await _apply(client, sid, cal_id)).status_code == 200
    run_id = await start_run(client, sid, run_type="sweep_pull", ramp_rate_rpm_s=200)
    await asyncio.sleep(1.0)

    await _patch_ignition(client, cal_id)
    applied = await _apply(client, sid, cal_id)

    assert applied.status_code == 200, applied.text
    assert applied.json()["mode"] == "live_tables"
    assert applied.json()["changed_tables"] == ["ignition_base"]
    await replace_calibration(client, cal_id, _overboost)
    refused = await _apply(client, sid, cal_id)
    assert (refused.status_code, refused.json()["code"]) == (409, "TABLE_NOT_LIVE_TUNABLE")
    run = await wait_run(client, run_id)
    assert run["state"] == "completed", run.get("abort_reason")
    await close_session(client, sid)


async def test_first_live_apply_diffs_against_loaded_version(client: httpx.AsyncClient) -> None:
    session = await create_session(client, vehicle_id=HATCH)
    sid, cal_id = session["session_id"], session["calibration_id"]
    run_id = await start_run(client, sid, run_type="sweep_pull", ramp_rate_rpm_s=200)
    await asyncio.sleep(1.0)

    await replace_calibration(client, cal_id, _overboost)
    refused = await _apply(client, sid, cal_id)

    await wait_run(client, run_id)
    await close_session(client, sid)
    assert (refused.status_code, refused.json()["code"]) == (409, "TABLE_NOT_LIVE_TUNABLE")
