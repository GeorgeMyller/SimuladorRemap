"""Autocura do hash dos cenários builtin no início da tentativa (002 T006/T015; D-02)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from scn_helpers import STOCK_HASH, vehicle_info

from simremap.scenarios.catalog import VehicleInfo

STOCK_ID = "stock-hatch-20t-gdi-oem-stage"
DRIFTED = "e" * 64


def drift_stock(scn: Any) -> None:
    """A v1 da série passa a clonar com outro hash (schema da calibração evoluiu)."""
    stock = scn.cals.items[STOCK_ID]
    scn.cals.items[STOCK_ID] = [replace(stock[0], content_hash=DRIFTED)]


async def start(scn: Any, headers: dict[str, str]) -> dict[str, Any]:
    resp = await scn.client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def test_builtin_uses_factory_clone_when_it_matches(scn: Any) -> None:
    headers = await scn.profile("lucas_turbo")
    before = await scn.services.catalog.get("stage1-oem")
    drift_stock(scn)
    clones_before = len(scn.cals.items)

    body = await start(scn, headers)

    clone = await scn.cals.get(body["calibration_id"])
    assert clone.content_hash == STOCK_HASH["hatch-20t-gdi"]
    assert scn.cals.factory_clones == 1
    assert len(scn.cals.items) == clones_before + 1  # sem clone órfão da série
    after = await scn.services.catalog.get("stage1-oem")
    assert after.scenario_sha256 == before.scenario_sha256
    assert body["scenario_sha256"] == before.scenario_sha256


async def test_builtin_resyncs_scenario_hash_when_factory_also_diverges(scn: Any) -> None:
    headers = await scn.profile("lucas_turbo")
    before = await scn.services.catalog.get("stage1-oem")
    drift_stock(scn)
    scn.cals.factory_hash.pop("hatch-20t-gdi")  # catálogo sem payload de fábrica

    body = await start(scn, headers)

    clone = await scn.cals.get(body["calibration_id"])
    after = await scn.services.catalog.get("stage1-oem")
    assert clone.content_hash == DRIFTED
    assert after.initial_calibration.content_hash == DRIFTED
    assert after.scenario_sha256 != before.scenario_sha256
    assert after.builtin is True and after.origin == "builtin"
    assert body["scenario_sha256"] == after.scenario_sha256
    await scn.drain()
    got = await scn.attempt(body["attempt_id"], headers)
    assert got["scenario_sha256"] == after.scenario_sha256
    # Segunda tentativa já casa com o hash ressincronizado.
    again = await start(scn, headers)
    assert again["scenario_sha256"] == after.scenario_sha256


async def test_factory_clone_skipped_when_catalog_hash_differs(scn: Any) -> None:
    def lookup(vehicle_id: str) -> VehicleInfo | None:
        info: VehicleInfo | None = vehicle_info(vehicle_id)
        if info is not None:
            info.factory_content_hash = lambda _p: "9" * 64
        return info

    headers = await scn.profile("lucas_turbo")
    drift_stock(scn)
    scn.services.catalog.vehicles = lookup
    clones_before = len(scn.cals.items)

    body = await start(scn, headers)

    assert scn.cals.factory_clones == 0
    assert len(scn.cals.items) == clones_before + 1
    after = await scn.services.catalog.get("stage1-oem")
    assert after.initial_calibration.content_hash == DRIFTED
    assert body["scenario_sha256"] == after.scenario_sha256


async def test_resync_refuses_non_builtin(scn: Any) -> None:
    from simremap.core.errors import SimRemapError
    from simremap.scenarios.catalog import example_challenge

    prof = await scn.profile("prof_marcos", "instructor")
    created = await scn.client.post(
        "/api/v1/scenarios", headers=prof, json={"scenario": example_challenge()}
    )
    assert created.status_code == 201, created.text
    try:
        await scn.services.catalog.resync_builtin_hash("challenge-400whp-e27", DRIFTED)
    except SimRemapError as exc:
        assert exc.error_code == "SCENARIO_INVALID"
    else:
        raise AssertionError("resync de cenário não builtin deveria falhar")
