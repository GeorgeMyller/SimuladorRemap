"""Desafios do instrutor e defeitos ocultos (T202; scenarios RF-03, RF-05, RF-08; D-18 do
data-model; EC-14)."""

from __future__ import annotations

import copy
from typing import Any

import httpx
from scn_env import ScnEnv
from scn_helpers import STOCK_HASH, RunSpec

from simremap.scenarios.catalog import example_challenge


def challenge(**over: Any) -> dict[str, Any]:
    doc = example_challenge()
    doc.update(over)
    return doc


async def create(
    scn: ScnEnv, headers: dict[str, str], doc: dict[str, Any], **extra: Any
) -> httpx.Response:
    return await scn.client.post(
        "/api/v1/scenarios", headers=headers, json={"scenario": doc, **extra}
    )


async def test_create_400whp_challenge_and_errors(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    resp = await create(scn, prof, challenge())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert resp.headers["Location"] == "/api/v1/scenarios/challenge-400whp-e27"
    assert body["vehicle_id"] == "coupe-30t-i6"
    assert body["origin"] == "local" and body["builtin"] is False
    assert body["author_nickname"] == "prof_marcos"
    assert body["initial_calibration"]["content_hash"] == STOCK_HASH["coupe-30t-i6"]  # recalculado
    assert len(body["scenario_sha256"]) == 64
    crit = {c["kind"]: c["threshold"] for c in body["criteria"]["criteria"]}
    assert crit["min_whp"] == 400 and crit["max_egt_c"] == 900
    dup = await create(scn, prof, challenge())
    assert dup.status_code == 409 and dup.json()["code"] == "SCENARIO_ALREADY_EXISTS"
    nov = await create(
        scn, prof, challenge(scenario_id="desafio-fantasma", vehicle_id="nao-existe-carro")
    )
    assert nov.status_code == 404 and nov.json()["code"] == "VEHICLE_NOT_FOUND"
    wrong = challenge(scenario_id="desafio-errado")
    wrong["criteria"]["criteria"][0]["comparator"] = "le"
    bad = await create(scn, prof, wrong)
    assert bad.status_code == 422 and bad.json()["code"] == "SCENARIO_INVALID"
    fuel = await create(scn, prof, challenge(scenario_id="desafio-e100", fuel_id="e100"))
    assert fuel.status_code == 422 and fuel.json()["code"] == "SCENARIO_INVALID"
    hints = challenge(scenario_id="desafio-dicas")
    hints["hints"] = [{"order": 2, "text": "x"}]
    schema = await create(scn, prof, hints)
    assert schema.status_code == 422 and schema.json()["code"] == "SCENARIO_INVALID"
    nocal = await create(
        scn, prof, challenge(scenario_id="desafio-cal"), initial_calibration_id="nao-existe"
    )
    assert nocal.status_code == 404 and nocal.json()["code"] == "CALIBRATION_NOT_FOUND"
    listed = (await scn.client.get("/api/v1/scenarios", params={"kind": "challenge"})).json()
    assert [s["scenario_id"] for s in listed] == ["challenge-400whp-e27"]


async def test_embedded_calibration_from_existing(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    record = await scn.cals.create(
        {"vehicle_id": "coupe-30t-i6", "profile_id": "oem-stage", "tables": {"x": 1}}, "minha"
    )
    resp = await create(
        scn,
        prof,
        challenge(scenario_id="desafio-embutido"),
        initial_calibration_id=record.calibration_id,
    )
    assert resp.status_code == 201, resp.text
    initial = resp.json()["initial_calibration"]
    assert initial["source"] == "embedded"
    assert initial["content_hash"] == record.content_hash
    student = await scn.profile("lucas_turbo")
    attempt = await scn.start("desafio-embutido", student)
    clone = await scn.cals.get(attempt["calibration_id"])
    assert clone.content_hash == record.content_hash


async def test_hidden_defect_redacted_for_student_and_fuel_pump_fault(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    doc = challenge(
        scenario_id="challenge-bomba-fraca",
        vehicle_id="hatch-20t-gdi",
        hidden_defect={"kind": "fuel_pump_weak", "fuel_pump_max_lph": 90},
    )
    doc["criteria"]["criteria"].append(
        {"criterion_id": "diagnostico", "kind": "defect_diagnosis", "comparator": "bool"}
    )
    doc["criteria"]["require_defect_diagnosis"] = True
    resp = await create(scn, prof, doc)
    assert resp.status_code == 201, resp.text
    student = await scn.profile("lucas_turbo")
    seen = (await scn.client.get("/api/v1/scenarios/challenge-bomba-fraca", headers=student)).json()
    assert seen["hidden_defect"] is None
    assert seen["has_hidden_defect"] is True
    anonymous = (await scn.client.get("/api/v1/scenarios/challenge-bomba-fraca")).json()
    assert anonymous["hidden_defect"] is None
    full = (await scn.client.get("/api/v1/scenarios/challenge-bomba-fraca", headers=prof)).json()
    assert full["hidden_defect"]["fuel_pump_max_lph"] == 90
    summary = next(
        s
        for s in (await scn.client.get("/api/v1/scenarios")).json()
        if s["scenario_id"] == "challenge-bomba-fraca"
    )
    assert summary["has_hidden_defect"] is True

    attempt = await scn.start("challenge-bomba-fraca", student)
    faults = scn.sim.sessions[attempt["session_id"]].view.physics_faults
    assert len(faults) == 1
    assert faults[0].kind == "fuel_pump_weak"
    assert faults[0].fuel_pump_max_lph == 90
    assert attempt.get("hidden_defect") is None
    # Diagnóstico declarado passa e a avaliação revela o defeito.
    scn.tune(attempt, RunSpec(peak_whp=402.0, egt_max_c=880.0))
    for _ in range(3):
        await scn.pull(attempt)
    ev = await scn.submit(attempt, student, declared_defect="fuel_pump_weak")
    diag = next(r for r in ev["results"] if r["criterion_id"] == "diagnostico")
    assert diag["passed"] is True
    assert ev["revealed_defect"]["kind"] == "fuel_pump_weak"


async def test_defect_mappings_and_wastegate_flag(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    student = await scn.profile("lucas_turbo")
    cases = {
        "desafio-bico": (
            {"kind": "injector_clogged", "cylinder": 2, "injector_flow_factor": 0.7},
            "injector_clogged",
        ),
        "desafio-iat": ({"kind": "iat_sensor_bias", "sensor_bias_c": 15}, "sensor_bias"),
        "desafio-wastegate": (
            {"kind": "wastegate_stuck", "stuck_position_pct": 0},
            "wastegate_stuck",
        ),
    }
    for sid, (defect, fault_kind) in cases.items():
        resp = await create(scn, prof, challenge(scenario_id=sid, hidden_defect=defect))
        assert resp.status_code == 201, resp.text
        attempt = await scn.start(sid, student)
        fault = scn.sim.sessions[attempt["session_id"]].view.physics_faults[0]
        assert fault.kind == fault_kind
        if fault_kind == "sensor_bias":
            assert fault.sensor_channel == "iat_c" and fault.sensor_bias == 15
        await scn.client.post(f"/api/v1/attempts/{attempt['attempt_id']}/abandon", headers=student)
    big = await create(
        scn,
        prof,
        challenge(
            scenario_id="desafio-cil",
            hidden_defect={"kind": "injector_clogged", "cylinder": 8, "injector_flow_factor": 0.7},
        ),
    )
    assert big.status_code == 422
    scn.app.state.settings = scn.app.state.settings.model_copy(
        update={"feature_defect_wastegate": False}
    )
    off = await create(
        scn,
        prof,
        challenge(
            scenario_id="desafio-wg2",
            hidden_defect={"kind": "wastegate_stuck", "stuck_position_pct": 100},
        ),
    )
    assert off.status_code == 422
    assert off.json()["code"] == "SCENARIO_INVALID"
    assert "defeito não suportado" in off.json()["detail"]
    listed = {s["scenario_id"]: s for s in (await scn.client.get("/api/v1/scenarios")).json()}
    assert listed["desafio-wastegate"]["available"] is False


async def test_defect_diagnosis_requires_defect(scn: ScnEnv) -> None:
    prof = await scn.profile("prof_marcos", "instructor")
    doc = copy.deepcopy(challenge(scenario_id="desafio-diag"))
    doc["criteria"]["criteria"].append(
        {"criterion_id": "diag", "kind": "defect_diagnosis", "comparator": "bool"}
    )
    resp = await create(scn, prof, doc)
    assert resp.status_code == 422
    assert resp.json()["code"] == "SCENARIO_INVALID"
