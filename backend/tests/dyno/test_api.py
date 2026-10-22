"""Endpoints E-06 a E-11 (T126; dyno RF-01, RF-06, RF-17, RF-18, RF-20, RF-21, RF-22, RF-26; D-14).

Puxadas curtas (``sweep_pull`` 2000 → 3000 rpm a 1000 rpm/s) mantêm o tempo de parede
baixo; o worker corre em ``thread`` com ``steps_per_tick = 10``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.dyno.contracts import DynoRun

SHORT = {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}
TERMINAL = {"completed", "aborted", "engine_failed"}


async def new_session(client: httpx.AsyncClient, **body: Any) -> str:
    resp = await client.post(
        "/api/v1/sessions", json={"vehicle_id": "hatch-20t-gdi", "seed": 3, **body}
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["session_id"])


async def wait_terminal(
    client: httpx.AsyncClient, run_id: str, timeout_s: float = 90.0
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        resp = await client.get(f"/api/v1/runs/{run_id}", params={"include_curve": "false"})
        body: dict[str, Any] = resp.json()
        if body["state"] in TERMINAL:
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("a puxada não terminou")


async def test_run_lifecycle_location_baseline_and_curves(dyno_client: httpx.AsyncClient) -> None:
    sid = await new_session(dyno_client)
    resp = await dyno_client.post(
        f"/api/v1/sessions/{sid}/runs", json={"run_type": "baseline_pull", "end_rpm": 3000}
    )
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert run["state"] == "arming"
    assert resp.headers["location"] == f"/api/v1/runs/{run['run_id']}"
    session = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert session["active_run_id"] == run["run_id"] and session["state"] == "running"
    done = await wait_terminal(dyno_client, run["run_id"])
    assert done["state"] == "completed"
    assert done["summary"]["peak_whp"] > 0 and done["curve"] == []
    session = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert session["baseline_run_id"] == run["run_id"]  # RF-06
    assert session["active_run_id"] is None and session["state"] == "ready"
    assert session["t_sim_s"] > 0
    raw = (await dyno_client.get(f"/api/v1/runs/{run['run_id']}", params={"curve": "raw"})).json()
    smooth = (await dyno_client.get(f"/api/v1/runs/{run['run_id']}")).json()
    assert len(raw["curve"]) == len(smooth["curve"]) > 10
    assert "lambda" in raw["curve"][0]
    assert raw["curve"] != smooth["curve"]
    assert DynoRun.model_validate(raw).curve_sha256 == raw["curve_sha256"]
    # Segunda puxada base não troca a referência.
    second = await dyno_client.post(
        f"/api/v1/sessions/{sid}/runs", json={"run_type": "baseline_pull", "end_rpm": 3000}
    )
    await wait_terminal(dyno_client, second.json()["run_id"])
    session = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert session["baseline_run_id"] == run["run_id"]


async def test_rf21_second_run_is_refused_and_rf17_abort(dyno_client: httpx.AsyncClient) -> None:
    sid = await new_session(dyno_client)
    first = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    assert first.status_code == 202
    second = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    assert second.status_code == 409
    assert second.json()["code"] == "RUN_IN_PROGRESS"
    rid = first.json()["run_id"]
    await asyncio.sleep(0.3)
    aborted = await dyno_client.post(f"/api/v1/sessions/{sid}/runs/{rid}/abort")
    assert aborted.status_code == 200, aborted.text
    assert aborted.json()["state"] == "aborted"
    assert aborted.json()["abort_reason"] == "user_abort"
    again = await dyno_client.post(f"/api/v1/sessions/{sid}/runs/{rid}/abort")
    assert again.status_code == 409 and again.json()["code"] == "RUN_NOT_ACTIVE"
    missing = await dyno_client.post(
        f"/api/v1/sessions/{sid}/runs/01JAB000000000000000000000/abort"
    )
    assert missing.status_code == 404 and missing.json()["code"] == "RUN_NOT_FOUND"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"run_type": "sweep_pull", "gear": 7}, "GEAR_NOT_AVAILABLE"),
        ({"run_type": "sweep_pull", "start_rpm": 3000, "end_rpm": 3400}, "RPM_RANGE_INVALID"),
        ({"run_type": "sweep_pull", "start_rpm": 6200}, "RPM_RANGE_INVALID"),
        (
            {"run_type": "steady_state_hold", "cells": [{"rpm": 9000, "pedal_pct": 50}]},
            "RPM_RANGE_INVALID",
        ),
        ({"run_type": "sweep_pull", "probe": {"ignition_offset_deg": 2}}, "PROBE_NOT_ALLOWED"),
        ({"run_type": "sweep_pull", "smoothing_window": 4}, "VALIDATION_FAILED"),
        ({"run_type": "steady_state_hold"}, "VALIDATION_FAILED"),
        ({"run_type": "sweep_pull", "probe": {"damage_enabled": True}}, "VALIDATION_FAILED"),
    ],
)
async def test_run_request_guards(
    dyno_client: httpx.AsyncClient, body: dict[str, Any], code: str
) -> None:
    sid = await new_session(dyno_client)
    resp = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=body)
    assert resp.json()["code"] == code, resp.text
    assert resp.status_code in (409, 422)


async def test_probe_allowed_with_attempt(dyno_client: httpx.AsyncClient) -> None:
    sid = await new_session(dyno_client, attempt_id="3f1a2b3c-4d5e-4f60-8a7b-9c0d1e2f3a4b")
    resp = await dyno_client.post(
        f"/api/v1/sessions/{sid}/runs", json={**SHORT, "probe": {"ignition_offset_deg": 2}}
    )
    assert resp.status_code == 202, resp.text
    done = await wait_terminal(dyno_client, resp.json()["run_id"])
    assert done["state"] == "completed"


async def test_rf20_engine_destroyed_guard(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    sid = await new_session(dyno_client)
    dyno_app.state.dyno_service.runtime(sid).update(engine_locked=True)
    resp = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    assert resp.status_code == 409
    problem = resp.json()
    assert problem["code"] == "ENGINE_DESTROYED"
    assert f"/api/v1/sessions/{sid}/engine/restore" in problem["detail"]


async def test_rf22_delete_with_active_run_aborts_with_session_closed(
    dyno_client: httpx.AsyncClient,
) -> None:
    sid = await new_session(dyno_client)
    run = (
        await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    ).json()
    await asyncio.sleep(0.2)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    assert loop.time() - t0 < 3.0
    stored = (await dyno_client.get(f"/api/v1/runs/{run['run_id']}")).json()
    assert stored["state"] == "aborted"
    assert stored["abort_reason"] == "session_closed"
    again = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    # rest-api E-09: sessão encerrada ⇒ 409 SESSION_CLOSED (003 QA; antes 404)
    assert (again.status_code, again.json()["code"]) == (409, "SESSION_CLOSED")


async def test_unknown_run(dyno_client: httpx.AsyncClient) -> None:
    resp = await dyno_client.get("/api/v1/runs/01JAB000000000000000000000")
    assert resp.status_code == 404 and resp.json()["code"] == "RUN_NOT_FOUND"
    bad = await dyno_client.get("/api/v1/runs/01JAB000000000000000000000", params={"curve": "x"})
    assert bad.status_code == 422


async def test_rf18_summary_survives_restart(
    dyno_app: FastAPI, settings_factory: Callable[..., Any]
) -> None:
    async with LifespanManager(dyno_app, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            sid = await new_session(c)
            run = (await c.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)).json()
            before = await wait_terminal(c, run["run_id"])
            full_before = (
                await c.get(f"/api/v1/runs/{run['run_id']}", params={"curve": "raw"})
            ).json()
    from simremap.api.main import create_app

    fresh = create_app(settings_factory(worker_mode="process"))
    async with LifespanManager(fresh, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as c:
            after = (await c.get(f"/api/v1/runs/{run['run_id']}", params={"curve": "raw"})).json()
            session = (await c.get(f"/api/v1/sessions/{sid}")).json()
    assert after["summary"] == before["summary"]
    assert after["curve"] == full_before["curve"]
    assert after["curve_sha256"] == full_before["curve_sha256"]
    assert session["state"] == "closed"
