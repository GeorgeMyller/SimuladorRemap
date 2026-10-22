"""Cenários base: carga idempotente e ``scenario_sha256`` por JCS (T201; scenarios RF-04,
RF-06; D-11; premissa OQ-06)."""

from __future__ import annotations

import copy
import hashlib
import json

import rfc8785
from scn_env import ScnEnv
from scn_helpers import STOCK_HASH

from simremap.scenarios.catalog import BUILTIN_IDS, builtin_documents, scenario_sha256
from simremap.scenarios.contracts import Scenario

# Hashes fixados com as calibrações de série da estação de teste (STOCK_HASH):
# recalculados de forma independente com ``rfc8785`` em ``independent``.
PINNED = {
    "stage1-oem": "c8adc4d9a0912a9235ffa173f549b67e06e53b65ca9ec0ac26b859c52002dc7b",
    "stage2-pops-bangs": "61d1e3d5ed09c48b5667c3fdc6b037322ff0abffa7aab8b8d32411b6be0c278d",
    "standalone-swap": "6174bb84875c132bdd756df7a2e6a78d489f3e5cd246ea1d09726eb6d572b02e",
    "defect-fuel-pump": "4719839dea8c2c6ea18fdb9a39397cb845cb5b0c3543e0c415918159f56f1e83",
    "defect-boost-leak": "36904fa832943079648c3ed430116ac4783625f560e79c809df089a751c3c325",
    "defect-lean-injector": "c08d921e78e37668cd6507e44aa319184e7bbd4d2c4a313701180028c244225d",
    "defect-wastegate-stuck": "ea8fb2c93ac23c7d234c19178d78c4bd253ed93f51935529d7ba06c7b799f777",
}


def independent(sid: str) -> str:
    doc = builtin_documents()[sid]
    doc["initial_calibration"]["content_hash"] = STOCK_HASH[doc["vehicle_id"]]
    data = Scenario.model_validate(doc).model_dump(mode="json")
    for key in ("created_at", "builtin", "origin", "scenario_sha256"):
        data.pop(key)
    defect = data["hidden_defect"]
    if defect is not None and defect["leak_area_mm2"] is None:
        defect.pop("leak_area_mm2")  # campo da 002 fora do hash quando vazio
    return hashlib.sha256(rfc8785.dumps(data)).hexdigest()


async def test_builtin_loaded_idempotently(scn: ScnEnv) -> None:
    resp = await scn.client.get("/api/v1/scenarios", params={"kind": "base"})
    assert resp.status_code == 200
    assert [s["scenario_id"] for s in resp.json()] == sorted(BUILTIN_IDS)
    again = await scn.services.catalog.load_builtin()
    assert set(again.values()) == {"unchanged"}
    rows = await scn.services.repo.list_scenarios("base")
    assert len(rows) == len(BUILTIN_IDS) == 7
    assert all(s.builtin and s.origin == "builtin" for s in rows)
    challenges = await scn.client.get("/api/v1/scenarios", params={"kind": "challenge"})
    assert challenges.json() == []
    bad = await scn.client.get("/api/v1/scenarios", params={"kind": "outro"})
    assert bad.status_code == 422


async def test_scenario_sha256_pinned_and_independent(scn: ScnEnv) -> None:
    for sid in BUILTIN_IDS:
        body = (await scn.client.get(f"/api/v1/scenarios/{sid}")).json()
        assert body["scenario_sha256"] == independent(sid) == PINNED[sid], sid
        assert body["builtin"] is True


async def test_base_values_and_premises(scn: ScnEnv) -> None:
    swap = (await scn.client.get("/api/v1/scenarios/standalone-swap")).json()
    crit = {c["kind"]: c for c in swap["criteria"]["criteria"]}
    assert crit["min_whp"]["threshold"] == 300  # OQ-06: 300 whp absolutos
    assert crit["min_knock_margin_deg"]["threshold"] == 2
    assert swap["fuel_id"] == "e100"
    assert swap["vehicle_id"] == "classic-20t-swap"
    assert swap["constraints"]["allowed_final_profiles"] == ["ft-pro", "m1-race", "ht-elite"]
    assert len(swap["hints"]) == 5
    stage2 = (await scn.client.get("/api/v1/scenarios/stage2-pops-bangs")).json()
    assert {c["kind"] for c in stage2["criteria"]["criteria"]} >= {
        "min_pop_events",
        "max_egt_overrun_c",
    }
    assert len(stage2["hints"]) == 4
    stage1 = (await scn.client.get("/api/v1/scenarios/stage1-oem")).json()
    assert len(stage1["hints"]) == 3
    assert stage1["initial_calibration"]["content_hash"] == STOCK_HASH["hatch-20t-gdi"]


def test_hash_changes_with_threshold_not_with_key_order() -> None:
    doc = builtin_documents()["stage1-oem"]
    doc["initial_calibration"]["content_hash"] = "a" * 64
    base = scenario_sha256(Scenario.model_validate(doc))
    reordered = json.loads(json.dumps(dict(reversed(list(doc.items())))))
    assert scenario_sha256(Scenario.model_validate(reordered)) == base
    changed = copy.deepcopy(doc)
    changed["criteria"]["criteria"][2]["threshold"] = 951
    assert scenario_sha256(Scenario.model_validate(changed)) != base
    meta = copy.deepcopy(doc)
    meta["origin"] = "builtin"
    meta["created_at"] = "2026-10-18T10:00:00Z"
    assert scenario_sha256(Scenario.model_validate(meta)) == base


async def test_scenarios_are_immutable(scn: ScnEnv) -> None:
    for method in ("PUT", "PATCH"):
        resp = await scn.client.request(method, "/api/v1/scenarios/stage1-oem", json={})
        assert resp.status_code == 405
        assert resp.json()["code"] == "METHOD_NOT_ALLOWED"


async def test_vehicle_missing_skips_builtin(scn: ScnEnv) -> None:
    catalog = scn.services.catalog
    original = catalog.vehicles
    catalog.vehicles = lambda vid: None if vid == "classic-20t-swap" else original(vid)
    outcome = await catalog.load_builtin()
    assert outcome["standalone-swap"] == "skipped"
    catalog.vehicles = original
