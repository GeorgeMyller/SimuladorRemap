"""Gestor de sessões: limite, ``DELETE``, ``seed``, ``fuel_id`` e ``physics_faults``.

T125; dyno RF-01, RF-02, RF-22, RF-23, RF-25; D-31.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from dyno_helpers import make_payload, modified_content

from simremap.dyno.assembly import assemble
from simremap.dyno.contracts import SEED_MAX, SEED_RANDOM_MAX
from simremap.dyno.session import draw_session_seed
from simremap.physics.contracts import PhysicsFault

HATCH = {"vehicle_id": "hatch-20t-gdi"}


async def create(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/api/v1/sessions", json={**HATCH, **body})


async def test_rf01_create_ready_session_with_location(dyno_client: httpx.AsyncClient) -> None:
    resp = await create(dyno_client, seed=11, sim_hz=500)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "ready"
    assert body["seed"] == 11 and body["sim_hz"] == 500
    assert body["calibration_id"] == "stock-hatch-20t-gdi-oem-stage"
    assert body["fuel_id"] == "e27" and body["physics_faults"] == []
    assert body["ecu_state"] == "oem" and body["engine_locked"] is False
    assert resp.headers["location"] == f"/api/v1/sessions/{body['session_id']}"
    got = await dyno_client.get(resp.headers["location"])
    assert got.status_code == 200
    assert got.json()["session_id"] == body["session_id"]


async def test_rf02_capacity_limit_and_delete_frees_slot(dyno_client: httpx.AsyncClient) -> None:
    first = await create(dyno_client)
    assert first.status_code == 201
    sid = first.json()["session_id"]
    second = await create(dyno_client)
    assert second.status_code == 409
    problem = second.json()
    assert problem["code"] == "SIM_CAPACITY_EXCEEDED"
    assert sid in problem["detail"]
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    closed = await dyno_client.get(f"/api/v1/sessions/{sid}")
    assert closed.status_code == 200 and closed.json()["state"] == "closed"
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 404
    third = await create(dyno_client)
    assert third.status_code == 201


async def test_rf23_seed_generated_when_omitted(dyno_client: httpx.AsyncClient) -> None:
    resp = await create(dyno_client)
    seed = resp.json()["seed"]
    assert isinstance(seed, int) and 0 <= seed <= SEED_RANDOM_MAX


def test_t031_drawn_seed_is_exact_in_javascript() -> None:
    """Sorteio em [0, 2^53 − 1]: o ``Number`` do JS representa a semente sem perda."""
    assert SEED_RANDOM_MAX == 2**53 - 1
    seeds = [draw_session_seed() for _ in range(2000)]
    assert all(0 <= s <= SEED_RANDOM_MAX for s in seeds)
    assert all(int(float(s)) == s for s in seeds)
    assert len(set(seeds)) > 1990


async def test_t031_client_seed_above_2_53_still_accepted(dyno_client: httpx.AsyncClient) -> None:
    resp = await create(dyno_client, seed=SEED_MAX)
    assert resp.status_code == 201, resp.text
    assert resp.json()["seed"] == SEED_MAX


async def test_rf25_fuel_and_physics_faults(dyno_client: httpx.AsyncClient) -> None:
    refused = await create(dyno_client, fuel_id="e100")
    assert refused.status_code == 409
    assert refused.json()["code"] == "FUEL_NOT_ALLOWED"
    assert refused.json()["allowed_fuel_ids"] == ["e27", "podium", "e0"]
    fault = {"kind": "fuel_pump_weak", "fuel_pump_max_lph": 90.0}
    ok = await create(dyno_client, fuel_id="podium", physics_faults=[fault])
    assert ok.status_code == 201, ok.text
    assert ok.json()["fuel_id"] == "podium"
    assert ok.json()["physics_faults"][0]["kind"] == "fuel_pump_weak"


def test_rf25_faults_reach_physics_config() -> None:
    fault = PhysicsFault(kind="fuel_pump_weak", fuel_pump_max_lph=90.0)
    parts = assemble(make_payload(physics_faults=[fault]))
    assert len(parts.physics.config.faults) == 1
    assert parts.physics.config.faults[0].kind == "fuel_pump_weak"
    plain = assemble(make_payload())
    assert plain.physics.config.faults == []
    assert plain.fuel.fuel_id == "e27"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"vehicle_id": "coupe-30t-i6"}, 404, "VEHICLE_NOT_FOUND"),
        ({**HATCH, "sim_hz": 50}, 422, "VALIDATION_FAILED"),
        ({**HATCH, "sim_hz": 2000}, 422, "VALIDATION_FAILED"),
        ({**HATCH, "calibration_id": "nao-existe"}, 404, "CALIBRATION_NOT_FOUND"),
        ({**HATCH, "fuel_id": "diesel"}, 422, "VALIDATION_FAILED"),
        ({**HATCH, "physics_faults": [{"kind": "injector_clogged", "cylinder": 6}]}, 422, None),
        ({**HATCH, "rig": {"accel_window_ticks": 20}}, 422, "VALIDATION_FAILED"),
    ],
)
async def test_session_validation_errors(
    dyno_client: httpx.AsyncClient, body: dict[str, Any], status: int, code: str | None
) -> None:
    resp = await dyno_client.post("/api/v1/sessions", json=body)
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    if code is not None:
        assert resp.json()["code"] == code


async def test_calibration_of_other_vehicle_is_refused(
    dyno_client: httpx.AsyncClient, calibration_source: Any
) -> None:
    calibration_source.add("cal-outro", modified_content(), vehicle_id="coupe-30t-i6")
    resp = await create(dyno_client, calibration_id="cal-outro")
    assert resp.status_code == 422
    assert resp.json()["code"] == "CALIBRATION_VEHICLE_MISMATCH"


async def test_unknown_session(dyno_client: httpx.AsyncClient) -> None:
    sid = "0" * 32
    for resp in (
        await dyno_client.get(f"/api/v1/sessions/{sid}"),
        await dyno_client.delete(f"/api/v1/sessions/{sid}"),
        await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "baseline_pull"}),
    ):
        assert resp.status_code == 404
        assert resp.json()["code"] == "SESSION_NOT_FOUND"


def test_catalog_vehicle_source_and_factory_calibration_fallback() -> None:
    from simremap.catalog.errors import VehicleNotValidated
    from simremap.catalog.loader import load_catalog_data
    from simremap.catalog.service import CatalogService, get_catalog, set_catalog
    from simremap.dyno.session import CatalogVehicleSource, RepositoryCalibrationSource

    previous = get_catalog()
    source = CatalogVehicleSource()
    try:
        set_catalog(CatalogService(previous.catalog, allow_drafts=True))
        vehicle = source.vehicle_for_session("hatch-20t-gdi")
        assert vehicle.vehicle_id == "hatch-20t-gdi"
        assert source.fuel_for_vehicle("hatch-20t-gdi", "e27").fuel_id == "e27"
        assert len(source.catalog_sha256()) == 64
        assert source.factory_calibration("hatch-20t-gdi", "oem-stage") is not None
        assert source.factory_calibration("hatch-20t-gdi", "m1-race") is None
        if vehicle.validation_status != "validated":
            set_catalog(CatalogService(load_catalog_data(), allow_drafts=False))
            with pytest.raises(VehicleNotValidated):
                source.vehicle_for_session("hatch-20t-gdi")
    finally:
        set_catalog(previous)
    calibrations = RepositoryCalibrationSource(None, source)
    import asyncio

    assert asyncio.run(calibrations.resolve("outra", "hatch-20t-gdi", "oem-stage")) is None
    # calibração de série do catálogo válida (knock_threshold 0–1): resolvida sem o banco
    resolved = asyncio.run(
        calibrations.resolve("stock-hatch-20t-gdi-oem-stage", "hatch-20t-gdi", "oem-stage")
    )
    assert resolved is not None and len(resolved.content_hash) == 64


async def test_disabled_ecu_profile_is_not_found(settings_factory: Any, tmp_path: Any) -> None:
    from asgi_lifespan import LifespanManager
    from dyno_helpers import FixtureCalibrationSource, make_dyno_app

    app = make_dyno_app(
        settings_factory(worker_mode="process", ecu_profiles_enabled="ft-pro"),
        FixtureCalibrationSource(),
    )
    async with LifespanManager(app, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await create(client)
    assert resp.status_code == 404
    assert resp.json()["code"] == "ECU_PROFILE_NOT_FOUND"
