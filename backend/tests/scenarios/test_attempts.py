"""Ciclo da tentativa (T203; scenarios RF-07, RF-08, RF-27; EC-13)."""

from __future__ import annotations

from dataclasses import replace

from scn_env import ScnEnv
from scn_helpers import STOCK_HASH, RunSpec

from simremap.dyno.contracts import RunState
from simremap.scenarios.catalog import example_challenge
from simremap.scenarios.contracts import derive_attempt_seed


async def test_start_preparing_then_in_progress_with_baseline(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    resp = await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "preparing"
    assert body["session_id"] and body["calibration_id"]
    assert resp.headers["Location"] == f"/api/v1/attempts/{body['attempt_id']}"
    assert body["seed"] == derive_attempt_seed(body["attempt_id"])
    clone = await scn.cals.get(body["calibration_id"])
    assert clone.content_hash == STOCK_HASH["hatch-20t-gdi"]  # = initial_calibration.content_hash

    await scn.drain()
    got = (await scn.client.get(f"/api/v1/attempts/{body['attempt_id']}", headers=headers)).json()
    assert got["state"] == "in_progress"
    assert got["baseline_run_id"] is not None
    assert got["baseline_peak_whp"] == 220.0
    assert got["runs"][0]["run_id"] == got["baseline_run_id"]
    assert got["runs"][0]["valid"] is True
    session = scn.sim.sessions[body["session_id"]].view
    assert session.attempt_id == body["attempt_id"]
    assert session.physics_faults == []
    assert session.seed == body["seed"]
    assert session.fuel_id == "e27"
    assert scn.sim.requests[0].run_type.value == "baseline_pull"
    assert scn.sim.requests[0].gear == 4


async def test_new_attempt_abandons_previous_and_deletes_session(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    first = (await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)).json()
    await scn.drain()
    second = await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert second.status_code == 201, second.text
    old = (await scn.client.get(f"/api/v1/attempts/{first['attempt_id']}", headers=headers)).json()
    assert old["state"] == "abandoned"
    assert first["session_id"] in scn.sim.deleted
    kinds = await scn.services.events.kinds_for(first["attempt_id"])
    assert "attempt_abandoned" in kinds


async def test_abandon_endpoint(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    other = await scn.profile("outro_aluno")
    body = (await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)).json()
    await scn.drain()
    url = f"/api/v1/attempts/{body['attempt_id']}/abandon"
    forbidden = await scn.client.post(url, headers=other)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "ATTEMPT_NOT_OWNED"
    resp = await scn.client.post(url, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "abandoned"
    again = await scn.client.post(url, headers=headers)
    assert again.status_code == 409
    assert again.json()["code"] == "ATTEMPT_NOT_IN_PROGRESS"


async def test_baseline_failure_is_failed_to_start(scn: ScnEnv) -> None:
    scn.sim.queue.append([RunSpec(state=RunState.ABORTED)])
    headers = await scn.profile("lucas_turbo")
    body = (await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)).json()
    await scn.drain()
    got = (await scn.client.get(f"/api/v1/attempts/{body['attempt_id']}", headers=headers)).json()
    assert got["state"] == "failed_to_start"
    assert got["failure_code"] == "BASELINE_FAILED"
    assert got["submissions"] == 0
    assert body["session_id"] in scn.sim.deleted


async def test_capacity_and_calibration_errors(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    scn.sim.capacity = 0
    resp = await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["code"] == "SIM_CAPACITY_EXCEEDED"
    scn.sim.capacity = 1
    scn.cals.fail = True
    resp = await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert resp.status_code == 503
    assert resp.json()["code"] == "CALIBRATION_SERVICE_UNAVAILABLE"
    scn.cals.fail = False
    # Série com hash diferente do fixado num cenário não builtin ⇒ 422 (builtin: autocura,
    # ver test_builtin_hash_resync.py).
    prof = await scn.profile("prof_marcos", "instructor")
    created = await scn.client.post(
        "/api/v1/scenarios", headers=prof, json={"scenario": example_challenge()}
    )
    assert created.status_code == 201, created.text
    stock = scn.cals.items["stock-coupe-30t-i6-oem-stage"]
    scn.cals.items["stock-coupe-30t-i6-oem-stage"] = [replace(stock[0], content_hash="e" * 64)]
    resp = await scn.client.post("/api/v1/scenarios/challenge-400whp-e27/attempts", headers=headers)
    assert resp.status_code == 422
    assert resp.json()["code"] == "SCENARIO_CALIBRATION_HASH_MISMATCH"
    assert scn.cals.factory_clones == 0
    missing = await scn.client.post("/api/v1/scenarios/nao-existe/attempts", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == "SCENARIO_NOT_FOUND"


async def test_events_have_no_nickname(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    body = (await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)).json()
    await scn.drain()
    rows = await scn.services.repo.events(attempt_id=body["attempt_id"])
    assert [r.kind for r in rows][:2] == ["attempt_started", "baseline_completed"]
    for row in rows:
        assert "lucas_turbo" not in str(row.data_json)
        assert "nickname" not in row.data_json


async def test_concurrent_classification_does_not_duplicate_runs(scn: ScnEnv) -> None:
    """Classificações simultâneas (baseline em fundo + GET da tentativa) não colidem na PK.

    Achado do E2E do Prof. Marcos (T219): o ``_baseline`` classifica as puxadas enquanto o
    ``GET /attempts/{id}`` também classifica; as duas viam ``attempt_run`` vazio e a segunda
    inserção falhava com ``UNIQUE constraint failed`` (500).
    """
    import asyncio

    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    await scn.pull(attempt)
    await scn.pull(attempt)
    service = scn.services.attempts
    row = await service.repo.get_attempt(attempt["attempt_id"])
    scenario = await scn.services.catalog.get("stage1-oem")
    results = await asyncio.gather(
        *(service._classify(row, scenario, retries=False) for _ in range(4))
    )
    assert all(len(r) == len(results[0]) == 3 for r in results)
    stored = await service.repo.runs_of(attempt["attempt_id"])
    assert len(stored) == 3
