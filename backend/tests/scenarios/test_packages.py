"""Pacotes assinados (T208; scenarios RF-18 a RF-21; D-11; G-04; EC-01, EC-02, EC-07, EC-08)."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any

import pytest
import rfc8785
from scn_env import ScnEnv
from scn_helpers import RunSpec

from simremap.core.errors import SimRemapError
from simremap.scenarios.catalog import example_challenge
from simremap.scenarios.packages import PackageService, package_sha256

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)


def rehash(pkg: dict[str, Any]) -> dict[str, Any]:
    pkg["sha256"] = hashlib.sha256(
        rfc8785.dumps(
            {
                "format_version": pkg["format_version"],
                "kind": pkg["kind"],
                "payload": pkg["payload"],
            }
        )
    ).hexdigest()
    return pkg


async def export(env: ScnEnv, headers: dict[str, str], **body: Any) -> tuple[dict[str, Any], str]:
    resp = await env.client.post("/api/v1/packages/export", headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["Content-Disposition"]
    return resp.json(), disposition


async def passed_attempt(
    scn: ScnEnv, nickname: str = "lucas_turbo"
) -> tuple[dict[str, Any], dict[str, str]]:
    headers = await scn.profile(nickname)
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, GOOD)
    await scn.pull(attempt)
    await scn.pull(attempt)
    ev = await scn.submit(attempt, headers)
    assert ev["passed"] is True
    return attempt, headers


async def test_export_attempt_hash_and_filename(scn: ScnEnv) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, disposition = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    independent = hashlib.sha256(
        rfc8785.dumps({"format_version": 1, "kind": "attempt", "payload": pkg["payload"]})
    ).hexdigest()
    assert pkg["sha256"] == independent
    assert pkg["hmac_sha256"] is None
    assert pkg["producer"]["nickname"] == "lucas_turbo"
    name = f"simremap-attempt-{attempt['attempt_id']}-{independent[:8]}.simremap.json"
    assert disposition == f'attachment; filename="{name}"'
    payload = pkg["payload"]
    assert payload["scenario"]["scenario_sha256"] == payload["attempt"]["scenario_sha256"]
    assert {r["run_id"] for r in payload["runs"]} >= set(payload["evaluation"]["evidence_run_ids"])
    assert all(r["curve_sha256"] for r in payload["runs"])
    assert isinstance(payload["attempt"]["seed"], str)  # > 2^53 − 1 ⇒ texto (JCS)
    again, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    assert again["sha256"] == pkg["sha256"]  # created_at fora do hash
    kinds = await scn.services.events.kinds_for(attempt["attempt_id"])
    assert "package_exported" in kinds


async def test_export_errors(scn: ScnEnv) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    resp = await scn.client.post(
        "/api/v1/packages/export",
        headers=headers,
        json={"kind": "attempt", "attempt_id": attempt["attempt_id"]},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "ATTEMPT_NOT_EVALUATED"
    missing = await scn.client.post(
        "/api/v1/packages/export",
        headers=headers,
        json={"kind": "challenge", "scenario_id": "nao-existe"},
    )
    assert missing.status_code == 404
    no_profile = await scn.client.post(
        "/api/v1/packages/export", json={"kind": "challenge", "scenario_id": "stage1-oem"}
    )
    assert no_profile.json()["code"] == "PLAYER_PROFILE_REQUIRED"


async def test_non_finite_export_is_rejected_with_path(
    scn: ScnEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt, headers = await passed_attempt(scn)
    service = scn.services.packages
    original = service._attempt_payload

    async def poisoned(attempt_id: str, include_logs: bool) -> tuple[dict[str, Any], str, str]:
        payload, ident, sid = await original(attempt_id, include_logs)
        payload["runs"][0]["summary"]["peak_whp"] = float("nan")
        return payload, ident, sid

    monkeypatch.setattr(service, "_attempt_payload", poisoned)
    resp = await scn.client.post(
        "/api/v1/packages/export",
        headers=headers,
        json={"kind": "attempt", "attempt_id": attempt["attempt_id"]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "PACKAGE_NOT_CANONICALIZABLE"
    assert resp.json()["path"] == "$.payload.runs[0].summary.peak_whp"


async def test_import_attempt_on_instructor_station(
    scn: ScnEnv, instructor_station: ScnEnv
) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    prof = await instructor_station.profile("prof_marcos", "instructor")
    student = await instructor_station.profile("aluno_x")
    body = json.dumps(pkg).encode()
    imp = instructor_station.client
    forbidden = await imp.post("/api/v1/packages/import", headers=student, content=body)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "INSTRUCTOR_ROLE_REQUIRED"

    first = await imp.post("/api/v1/packages/import", headers=prof, content=body)
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["already_imported"] is False
    assert result["evaluation_mismatch"] is False
    assert (
        result["recomputed_evaluation"]["evaluation_sha256"]
        == pkg["payload"]["evaluation"]["evaluation_sha256"]
    )
    second = await imp.post("/api/v1/packages/import", headers=prof, content=body)
    assert second.status_code == 200
    assert second.json()["already_imported"] is True
    page = (await imp.get("/api/v1/attempts", headers=prof, params={"origin": "imported"})).json()
    assert len(page["items"]) == 1
    row = page["items"][0]
    assert row["nickname"] == "lucas_turbo"
    assert row["package_sha256"] == pkg["sha256"]
    assert row["producer_install_id"] == pkg["producer"]["install_id"]
    assert row["last_evaluation"]["passed"] is True
    assert row["imported_at"] is not None


async def test_tampering_is_rejected_and_nothing_written(
    scn: ScnEnv, instructor_station: ScnEnv
) -> None:
    attempt, headers = await passed_attempt(scn)
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    prof = await instructor_station.profile("prof_marcos", "instructor")
    imp = instructor_station.client
    repo = instructor_station.services.repo

    tampered = copy.deepcopy(pkg)
    crit = tampered["payload"]["scenario"]["criteria"]["criteria"]
    egt = next(c for c in crit if c["criterion_id"] == "egt")
    egt["threshold"] = 951  # 1 dígito alterado num limiar
    resp = await imp.post("/api/v1/packages/import", headers=prof, content=json.dumps(tampered))
    assert resp.status_code == 422
    problem = resp.json()
    assert problem["code"] == "PACKAGE_HASH_MISMATCH"
    assert problem["expected_sha256"] == pkg["sha256"]
    assert problem["actual_sha256"] != pkg["sha256"]

    future = copy.deepcopy(pkg)
    future["format_version"] = 2
    resp = await imp.post("/api/v1/packages/import", headers=prof, content=json.dumps(future))
    assert resp.json()["code"] == "PACKAGE_FORMAT_UNSUPPORTED"
    raw = json.dumps(pkg)
    resp = await imp.post("/api/v1/packages/import", headers=prof, content=raw[: len(raw) // 2])
    assert resp.json()["code"] == "PACKAGE_MALFORMED"
    nan = raw.replace('"peak_whp": 262.0', '"peak_whp": NaN', 1)
    resp = await imp.post("/api/v1/packages/import", headers=prof, content=nan)
    assert resp.json()["code"] == "PACKAGE_NOT_CANONICALIZABLE"
    bad_schema = rehash({**copy.deepcopy(pkg), "kind": "attempt"})
    bad_schema["payload"]["attempt"]["state"] = "voando"
    rehash(bad_schema)
    resp = await imp.post("/api/v1/packages/import", headers=prof, content=json.dumps(bad_schema))
    assert resp.json()["code"] == "PACKAGE_SCHEMA_INVALID"

    # EC-02: limite de EGT 900 → 990 com o hash do pacote recalculado.
    forged = copy.deepcopy(pkg)
    crit = forged["payload"]["scenario"]["criteria"]["criteria"]
    next(c for c in crit if c["criterion_id"] == "egt")["threshold"] = 990
    resp = await imp.post(
        "/api/v1/packages/import", headers=prof, content=json.dumps(rehash(forged))
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "SCENARIO_VERSION_MISMATCH"

    assert await repo.imported_package(pkg["sha256"]) is None
    rows, _ = await repo.list_attempts(
        scenario_id=None, origin=None, profile_id=None, cursor=None, limit=10
    )
    assert rows == []


async def test_declared_evaluation_differs_from_recomputed(
    scn: ScnEnv, instructor_station: ScnEnv
) -> None:
    headers = await scn.profile("lucas_turbo")
    attempt = await scn.start("stage1-oem", headers)
    scn.tune(attempt, RunSpec(peak_whp=230.0))
    await scn.pull(attempt)
    await scn.pull(attempt)
    ev = await scn.submit(attempt, headers)
    assert ev["passed"] is False
    pkg, _ = await export(scn, headers, kind="attempt", attempt_id=attempt["attempt_id"])
    forged = copy.deepcopy(pkg)
    forged["payload"]["evaluation"]["passed"] = True
    forged["payload"]["evaluation"]["evaluation_sha256"] = "0" * 64
    prof = await instructor_station.profile("prof_marcos", "instructor")
    resp = await instructor_station.client.post(
        "/api/v1/packages/import", headers=prof, content=json.dumps(rehash(forged))
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["evaluation_mismatch"] is True
    assert body["recomputed_evaluation"]["passed"] is False
    got = await instructor_station.attempt(body["attempt_id"], prof)
    assert got["evaluation_mismatch"] is True
    assert got["last_evaluation"]["passed"] is False


async def test_challenge_round_trip(scn: ScnEnv, instructor_station: ScnEnv) -> None:
    prof = await instructor_station.profile("prof_marcos", "instructor")
    doc = example_challenge()
    doc["hidden_defect"] = {"kind": "fuel_pump_weak", "fuel_pump_max_lph": 90}
    resp = await instructor_station.client.post(
        "/api/v1/scenarios", headers=prof, json={"scenario": doc}
    )
    assert resp.status_code == 201, resp.text
    pkg, disposition = await export(
        instructor_station, prof, kind="challenge", scenario_id=doc["scenario_id"]
    )
    assert "simremap-challenge-challenge-400whp-e27-" in disposition
    assert pkg["payload"]["scenario"]["hidden_defect"]["kind"] == "fuel_pump_weak"
    student = await scn.profile("lucas_turbo")
    imp = await scn.client.post("/api/v1/packages/import", headers=student, content=json.dumps(pkg))
    assert imp.status_code == 201, imp.text
    assert imp.json()["kind"] == "challenge"
    local = (
        await scn.client.get(f"/api/v1/scenarios/{doc['scenario_id']}", headers=student)
    ).json()
    assert local["origin"] == "imported"
    assert local["hidden_defect"] is None and local["has_hidden_defect"] is True
    assert local["scenario_sha256"] == resp.json()["scenario_sha256"]
    again = await scn.client.post(
        "/api/v1/packages/import", headers=student, content=json.dumps(pkg)
    )
    assert again.status_code == 200 and again.json()["already_imported"] is True


async def test_g04_1000_seeded_mutations_all_hash_mismatch(scn: ScnEnv) -> None:
    headers = await scn.profile("prof_marcos", "instructor")
    pkg, _ = await export(scn, headers, kind="challenge", scenario_id="stage2-pops-bangs")
    rng = random.Random(8785)

    def leaves(node: Any, path: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        if isinstance(node, dict):
            return [p for k, v in node.items() for p in leaves(v, (*path, k))]
        if isinstance(node, list):
            return [p for i, v in enumerate(node) for p in leaves(v, (*path, i))]
        return [path]

    paths = leaves(pkg["payload"])
    rejected = 0
    for _ in range(1000):
        mutated = copy.deepcopy(pkg)
        path = rng.choice(paths)
        parent = mutated["payload"]
        for key in path[:-1]:
            parent = parent[key]
        value = parent[path[-1]]
        if isinstance(value, bool) or value is None:
            parent[path[-1]] = not value if isinstance(value, bool) else 0
        elif isinstance(value, int | float):
            parent[path[-1]] = value + rng.choice([1, 2, 5, 9])
        else:
            text = str(value)
            i = rng.randrange(len(text)) if text else 0
            ch = text[i] if text else "a"
            repl = "b" if ch == "a" else "a"
            parent[path[-1]] = text[:i] + repl + text[i + 1 :]
        try:
            PackageService.parse(json.dumps(mutated).encode())
        except SimRemapError as exc:
            assert exc.error_code == "PACKAGE_HASH_MISMATCH"
            rejected += 1
    assert rejected == 1000
    assert package_sha256(1, pkg["kind"], pkg["payload"]) == pkg["sha256"]
