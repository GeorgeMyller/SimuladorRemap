"""Endpoints E-30 a E-45 (T210; scenarios RF-02, RF-10, RF-12, RF-23; D-REST-07; EC-15)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from scn_env import ScnEnv
from scn_helpers import RunSpec

from simremap.core.errors import catalog
from simremap.db.models.scenarios import AttemptRow, EvaluationRow
from simremap.scenarios.errors import SCENARIO_ERROR_CODES

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)

E30_E45 = {
    ("get", "/api/v1/profiles"),
    ("post", "/api/v1/profiles"),
    ("get", "/api/v1/scenarios"),
    ("post", "/api/v1/scenarios"),
    ("get", "/api/v1/scenarios/{scenario_id}"),
    ("get", "/api/v1/scenarios/{scenario_id}/stats"),
    ("post", "/api/v1/scenarios/{scenario_id}/attempts"),
    ("get", "/api/v1/attempts"),
    ("get", "/api/v1/attempts/{attempt_id}"),
    ("post", "/api/v1/attempts/{attempt_id}/hints"),
    ("post", "/api/v1/attempts/{attempt_id}/abandon"),
    ("post", "/api/v1/attempts/{attempt_id}/submit"),
    ("get", "/api/v1/attempts/{attempt_id}/evaluation"),
    ("post", "/api/v1/attempts/{attempt_id}/replay"),
    ("post", "/api/v1/packages/export"),
    ("post", "/api/v1/packages/import"),
}


async def test_openapi_lists_16_endpoints_and_codes(scn: ScnEnv) -> None:
    spec = (await scn.client.get("/openapi.json")).json()
    found = {
        (method, path)
        for path, item in spec["paths"].items()
        for method in item
        if (method, path) in E30_E45
    }
    assert found == E30_E45
    for code, status, _ in SCENARIO_ERROR_CODES:
        assert catalog()[code].status == status
    assert "VALIDATION_ERROR" not in catalog()


async def test_submit_location_and_evaluation_flow(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    await scn.pull(attempt)
    await scn.pull(attempt)
    url = f"/api/v1/attempts/{attempt['attempt_id']}"
    none = await scn.client.get(f"{url}/evaluation", headers=headers)
    assert none.status_code == 404 and none.json()["code"] == "EVALUATION_NOT_FOUND"
    resp = await scn.client.post(
        f"{url}/submit", headers=headers, json={"calibration_id": attempt["calibration_id"]}
    )
    assert resp.status_code == 202
    assert resp.json() == {
        "attempt_id": attempt["attempt_id"],
        "submission_index": 1,
        "evaluation_status": "pending",
    }
    assert resp.headers["Location"] == f"{url}/evaluation?submission=1"
    pending = await scn.client.get(f"{url}/evaluation", headers=headers)
    assert pending.status_code == 200
    await scn.drain()
    ev = (await scn.client.get(f"{url}/evaluation?submission=1", headers=headers)).json()
    assert ev["status"] == "completed" and ev["passed"] is True
    assert (
        ev["calibration_content_hash"]
        == (await scn.cals.get(attempt["calibration_id"])).content_hash
    )
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert got["state"] == "passed"
    assert got["last_evaluation"]["evaluation_sha256"] == ev["evaluation_sha256"]
    assert attempt["session_id"] in scn.sim.deleted
    terminal = await scn.client.post(
        f"{url}/submit", headers=headers, json={"calibration_id": attempt["calibration_id"]}
    )
    assert terminal.status_code == 409 and terminal.json()["code"] == "ATTEMPT_NOT_IN_PROGRESS"
    summary = next(
        s
        for s in (await scn.client.get("/api/v1/scenarios", headers=headers)).json()
        if s["scenario_id"] == "stage1-oem"
    )
    assert summary["last_evaluation_passed"] is True


async def test_submit_errors(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    other = await scn.profile("intruso")
    attempt = await scn.start("stage1-oem", headers)
    url = f"/api/v1/attempts/{attempt['attempt_id']}/submit"
    body = {"calibration_id": attempt["calibration_id"]}
    assert (await scn.client.post(url, headers=other, json=body)).json()[
        "code"
    ] == "ATTEMPT_NOT_OWNED"
    foreign = await scn.client.post(
        url, headers=headers, json={"calibration_id": "outra-calibracao"}
    )
    assert foreign.status_code == 422 and foreign.json()["code"] == "CALIBRATION_NOT_IN_ATTEMPT"
    extra = await scn.client.post(url, headers=headers, json={**body, "nota": 10})
    assert extra.status_code == 422
    scn.sim.sessions[attempt["session_id"]].view = scn.sim.sessions[
        attempt["session_id"]
    ].view.model_copy(update={"active_run_id": "01J00000000000000000000099"})
    busy = await scn.client.post(url, headers=headers, json=body)
    assert busy.status_code == 409 and busy.json()["code"] == "RUN_IN_PROGRESS"
    scn.sim.sessions[attempt["session_id"]].view = scn.sim.sessions[
        attempt["session_id"]
    ].view.model_copy(update={"active_run_id": None})
    for _ in range(5):
        ok = await scn.client.post(url, headers=headers, json=body)
        assert ok.status_code == 202, ok.text
        await scn.drain()
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert got["state"] == "failed_final"
    assert got["submissions"] == 5
    kinds = await scn.services.events.kinds_for(attempt["attempt_id"])
    assert kinds.count("attempt_failed") == 5


async def test_submission_limit_reached(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    await scn.services.repo.update_attempt(attempt["attempt_id"], submissions=5)
    resp = await scn.client.post(
        f"/api/v1/attempts/{attempt['attempt_id']}/submit",
        headers=headers,
        json={"calibration_id": attempt["calibration_id"]},
    )
    assert resp.status_code == 409 and resp.json()["code"] == "SUBMISSION_LIMIT_REACHED"


async def test_explicit_run_ids_and_ignored(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    a = await scn.pull(attempt)
    gear = await scn.pull(attempt, gear=3)
    b = await scn.pull(attempt)
    ev = await scn.submit(attempt, headers, run_ids=[a, gear, b, "01J99999999999999999999999"])
    assert ev["evidence_run_ids"] == [a, b]
    assert f"{gear}:gear_mismatch" in ev["ignored_runs"]
    assert "01J99999999999999999999999:run_not_in_attempt" in ev["ignored_runs"]
    assert ev["passed"] is True


async def test_attempt_pagination_by_cursor(scn: ScnEnv) -> None:
    headers = await scn.profile("prof_marcos", "instructor")
    repo = scn.services.repo
    base = datetime(2026, 10, 1, tzinfo=UTC)
    for i in range(60):
        await repo.add_attempt(
            AttemptRow(
                id=str(uuid.uuid4()),
                scenario_id="stage1-oem",
                nickname=f"aluno_{i:02d}",
                origin="imported",
                state="passed",
                calibration_id="c",
                seed=i,
                producer_install_id=str(uuid.uuid4()),
                package_sha256=f"{i:064x}",
                started_at=base + timedelta(minutes=i),
                updated_at=base,
            )
        )
    first = await scn.client.get(
        "/api/v1/attempts",
        headers=headers,
        params={"origin": "imported", "scenario_id": "stage1-oem", "limit": 50},
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) == 50
    assert page["items"][0]["nickname"] == "aluno_59"
    assert page["next_cursor"] is not None
    second = (
        await scn.client.get(
            "/api/v1/attempts",
            headers=headers,
            params={"origin": "imported", "cursor": page["next_cursor"]},
        )
    ).json()
    assert len(second["items"]) == 10
    assert second["next_cursor"] is None
    ids = {i["attempt_id"] for i in page["items"]} | {i["attempt_id"] for i in second["items"]}
    assert len(ids) == 60
    local = (
        await scn.client.get("/api/v1/attempts", headers=headers, params={"origin": "local"})
    ).json()
    assert local["items"] == []
    bad = await scn.client.get("/api/v1/attempts", headers=headers, params={"limit": 500})
    assert bad.status_code == 422
    junk = await scn.client.get("/api/v1/attempts", headers=headers, params={"cursor": "%%%"})
    assert junk.status_code == 422
    missing = await scn.client.get(f"/api/v1/attempts/{uuid.uuid4()}", headers=headers)
    assert missing.status_code == 404 and missing.json()["code"] == "ATTEMPT_NOT_FOUND"


async def test_time_limit_expires_attempt(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    from simremap.scenarios.catalog import example_challenge

    doc = example_challenge()
    doc["scenario_id"] = "desafio-relogio"
    doc["constraints"]["time_limit_min"] = 10
    assert (
        await scn.client.post("/api/v1/scenarios", headers=prof, json={"scenario": doc})
    ).status_code == 201
    student = await scn.profile("lucas_turbo")
    attempt = await scn.start("desafio-relogio", student)
    old = datetime.now(UTC) - timedelta(minutes=11)
    await scn.services.repo.update_attempt(attempt["attempt_id"], started_at=old)
    got = await scn.attempt(attempt["attempt_id"], student)
    assert got["state"] == "expired"
    assert attempt["session_id"] in scn.sim.deleted


async def test_recover_interrupted_evaluations(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    repo = scn.services.repo
    await repo.update_attempt(attempt["attempt_id"], state="evaluating", submissions=1)
    from simremap.scenarios.evaluator import pending_evaluation

    eid = str(uuid.uuid4())
    created = datetime.now(UTC) - timedelta(minutes=6)
    pending = pending_evaluation(attempt["attempt_id"], 1, evaluation_id=eid, created_at=created)
    await repo.add_evaluation(
        EvaluationRow(
            id=eid,
            attempt_id=attempt["attempt_id"],
            submission_index=1,
            status="pending",
            result_json={"evaluation": pending.model_dump(mode="json")},
            created_at=created,
        )
    )
    outcome = await scn.services.attempts.recover()
    assert outcome["evaluations_interrupted"] == 1
    ev = (
        await scn.client.get(
            f"/api/v1/attempts/{attempt['attempt_id']}/evaluation", headers=headers
        )
    ).json()
    assert ev["status"] == "error" and ev["error_code"] == "EVALUATION_INTERRUPTED"
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert got["state"] == "in_progress" and got["submissions"] == 0


async def test_trace_unavailable_on_submit(scn: ScnEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    a = await scn.pull(attempt)
    scn.sim.fail_logs.add(a)
    from simremap.scenarios import attempts as mod

    monkeypatch.setattr(mod, "TRACE_RETRY_DELAYS_S", (0.0, 0.0, 0.0))
    ev = await scn.submit(attempt, headers)
    assert ev["status"] == "error" and ev["error_code"] == "TRACE_UNAVAILABLE"
    got = await scn.attempt(attempt["attempt_id"], headers)
    assert got["submissions"] == 0 and got["state"] == "in_progress"


@pytest.mark.parametrize("flag", [False])
async def test_feature_flag_off_returns_404(
    settings_factory: Callable[..., Any], flag: bool
) -> None:
    from scn_helpers import FakeCalibrations, FakeSimulation, fake_vehicles

    from simremap.api.main import create_app

    app = create_app(settings_factory(feature_scenarios=flag))
    cals = FakeCalibrations()
    app.state.scenarios_calibration_port = cals
    app.state.scenarios_sim_port = FakeSimulation(cals)
    app.state.scenarios_vehicle_lookup = fake_vehicles
    async with LifespanManager(app) as manager:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=manager.app), base_url="http://t"
        ) as client:
            resp = await client.get("/api/v1/scenarios")
            assert resp.status_code == 404
            assert resp.json()["code"] == "ROUTE_NOT_FOUND"
