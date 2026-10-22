"""Replay de tentativas importadas (T209; scenarios RF-22; EC-03)."""

from __future__ import annotations

import copy
import json
from typing import Any

from scn_env import ScnEnv
from scn_helpers import RunSpec

from simremap.scenarios.replay import compare_run
from tests.scenarios.test_packages import export, passed_attempt, rehash

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)


async def imported(scn: ScnEnv, station: ScnEnv, pkg: dict[str, Any]) -> tuple[str, dict[str, str]]:
    prof = await station.profile("prof_marcos", "instructor")
    resp = await station.client.post(
        "/api/v1/packages/import", headers=prof, content=json.dumps(pkg)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["attempt_id"], prof


def teach(station: ScnEnv, pkg: dict[str, Any]) -> None:
    """A estação do instrutor simula a mesma física: mesmo comportamento por hash."""
    station.sim.behaviour[station.cals.hash_of(_content(pkg))] = GOOD


def _content(pkg: dict[str, Any]) -> dict[str, Any]:
    cal = pkg["payload"]["calibration"]
    keys = ("vehicle_id", "profile_id", "fuel_model", "tables", "strategies", "profile_params")
    return {k: cal[k] for k in keys if k in cal}


async def test_honest_attempt_is_verified(scn: ScnEnv, instructor_station: ScnEnv) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    teach(instructor_station, pkg)
    attempt_id, prof = await imported(scn, instructor_station, pkg)
    resp = await instructor_station.client.post(
        f"/api/v1/attempts/{attempt_id}/replay", headers=prof
    )
    assert resp.status_code == 202, resp.text
    assert resp.json()["replay_status"] == "running"
    assert resp.json()["runs_to_replay"] == 2
    await instructor_station.drain()
    got = await instructor_station.attempt(attempt_id, prof)
    assert got["replay_status"] == "verified"
    assert got["replay_mismatch_run_ids"] == []
    assert instructor_station.sim.active() == []  # sessões de replay encerradas


async def test_edited_curve_is_mismatch(scn: ScnEnv, instructor_station: ScnEnv) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    forged = copy.deepcopy(pkg)
    target = forged["payload"]["evaluation"]["evidence_run_ids"][0]
    run = next(r for r in forged["payload"]["runs"] if r["run_id"] == target)
    run["curve"][-1]["power_wheel_kw_corr"] += 30.0  # curva editada, curve_sha256 antigo
    teach(instructor_station, forged)
    attempt_id, prof = await imported(scn, instructor_station, rehash(forged))
    await instructor_station.client.post(f"/api/v1/attempts/{attempt_id}/replay", headers=prof)
    await instructor_station.drain()
    got = await instructor_station.attempt(attempt_id, prof)
    assert got["replay_status"] == "mismatch"
    assert got["replay_mismatch_run_ids"] == [target]


async def test_forged_summary_detected_by_reexecution(
    scn: ScnEnv, instructor_station: ScnEnv
) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    teach(instructor_station, pkg)
    instructor_station.sim.behaviour[instructor_station.cals.hash_of(_content(pkg))] = RunSpec(
        peak_whp=235.0
    )
    attempt_id, prof = await imported(scn, instructor_station, pkg)
    await instructor_station.client.post(f"/api/v1/attempts/{attempt_id}/replay", headers=prof)
    await instructor_station.drain()
    got = await instructor_station.attempt(attempt_id, prof)
    assert got["replay_status"] == "mismatch"
    assert len(got["replay_mismatch_run_ids"]) == 2


async def test_incompatible_version_and_role(scn: ScnEnv, instructor_station: ScnEnv) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    old = copy.deepcopy(pkg)
    old["producer"]["app_version"] = "0.0.1"  # fora do hash
    attempt_id, prof = await imported(scn, instructor_station, old)
    student = await instructor_station.profile("aluno_x")
    denied = await instructor_station.client.post(
        f"/api/v1/attempts/{attempt_id}/replay", headers=student
    )
    assert denied.status_code == 403
    resp = await instructor_station.client.post(
        f"/api/v1/attempts/{attempt_id}/replay", headers=prof
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "REPLAY_VERSION_INCOMPATIBLE"
    got = await instructor_station.attempt(attempt_id, prof)
    assert got["replay_status"] == "incompatible_version"
    local = await scn.client.post(
        f"/api/v1/attempts/{attempt['attempt_id']}/replay", headers=headers
    )
    assert local.status_code == 403


def test_compare_run_requires_declared_hash() -> None:
    assert compare_run({"curve_sha256": None}, None) is False  # type: ignore[arg-type]
