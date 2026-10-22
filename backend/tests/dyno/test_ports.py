"""Adaptadores das portas (ecu-core, dano, ecu-profiles), persistência e perda do worker."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from simremap.dyno.output_router import OutputRouter
from simremap.dyno.ports import DynoDamagePort, DynoEcuSessionPort, DynoProfileSessionPort
from simremap.dyno.repository import DynoRepository
from simremap.profiles.session_port import EcuSessionInfo, EcuSwapCommand

SHORT = {"run_type": "sweep_pull", "end_rpm": 3000, "ramp_rate_rpm_s": 1000}


async def new_session(client: httpx.AsyncClient) -> str:
    resp = await client.post("/api/v1/sessions", json={"vehicle_id": "hatch-20t-gdi", "seed": 9})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["session_id"])


async def wait_terminal(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    for _ in range(600):
        body: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if body["state"] in ("completed", "aborted", "engine_failed"):
            return body
        await asyncio.sleep(0.1)
    raise AssertionError("a puxada não terminou")


async def test_ports_are_published(dyno_client: httpx.AsyncClient, dyno_app: FastAPI) -> None:
    state = dyno_app.state
    assert isinstance(state.ecu_session_port, DynoEcuSessionPort)
    assert isinstance(state.damage_port, DynoDamagePort)
    assert isinstance(state.profiles_session_port, DynoProfileSessionPort)
    assert state.dyno_stream_hub is state.dyno_service.streams


async def test_ecu_port_session_info(dyno_client: httpx.AsyncClient, dyno_app: FastAPI) -> None:
    port: DynoEcuSessionPort = dyno_app.state.ecu_session_port
    assert await port.get_session("0" * 32) is None
    sid = await new_session(dyno_client)
    info = await port.get_session(sid)
    assert info is not None
    assert info.vehicle_id == "hatch-20t-gdi" and info.profile_id == "oem-stage"
    assert info.run_active is False
    assert info.initial_calibration_id == "stock-hatch-20t-gdi-oem-stage"
    rt = dyno_app.state.dyno_service.runtime(sid)
    assert info.initial_calibration_version == rt.calibration.version  # base do 1.º diff (B2)
    await port.cancel_apply(sid, "nada")
    await port.cancel_apply("0" * 32, "nada")


async def test_damage_port_health_restore_and_closed_view(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    sid = await new_session(dyno_client)
    health = await dyno_client.get(f"/api/v1/sessions/{sid}/engine/health")
    assert health.status_code == 200, health.text
    assert health.json()["intact"] is True
    port: DynoDamagePort = dyno_app.state.damage_port
    assert len(await port.rod_weights(sid)) == 4
    run = (
        await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    ).json()
    busy = await dyno_client.post(f"/api/v1/sessions/{sid}/engine/restore")
    assert busy.status_code == 409 and busy.json()["code"] == "RUN_IN_PROGRESS"
    view = await port.get_session(sid)
    assert view is not None and view.active_run_id == run["run_id"]
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    closed = await port.get_session(sid)
    assert closed is not None and closed.closed
    assert await port.live_health(sid, True) is None
    assert await port.rod_weights(sid) == []
    assert (await port.get_run(run["run_id"])) is not None
    assert await port.get_session("0" * 32) is None


async def test_profiles_port_swap_and_setup_guard(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    port: DynoProfileSessionPort = dyno_app.state.profiles_session_port
    sid = await new_session(dyno_client)
    info = await port.get_session(sid)
    assert isinstance(info, EcuSessionInfo)
    assert info.profile_id == "oem-stage" and not info.closed and not info.fuel_mismatch_suspected
    command = EcuSwapCommand(
        request_id="swap-1",
        session_id=sid,
        profile_id="ft-pro",
        previous_profile_id="oem-stage",
        ecu_state="awaiting_base_setup",
    )
    applied = await port.swap_ecu(sid, command)
    assert applied >= 0.0
    session = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert session["profile_id"] == "ft-pro" and session["ecu_state"] == "awaiting_base_setup"

    class PendingGuard:
        def can_start_run(self, session_id: str) -> list[str]:
            return ["injectors.flow", "base_map"]

    dyno_app.state.profiles_guard = PendingGuard()
    resp = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    assert resp.status_code == 409
    assert resp.json()["code"] == "ECU_SETUP_INCOMPLETE"
    assert resp.json()["pending"] == ["injectors.flow", "base_map"]
    await port.cancel_swap(sid, "swap-1")
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    closed = await port.get_session(sid)
    assert closed is not None and closed.closed
    assert await port.get_session("0" * 32) is None
    with pytest.raises(Exception, match="não existe"):
        await port.swap_ecu(sid, command)


async def test_worker_lost_aborts_run_and_refuses_new_runs(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    sid = await new_session(dyno_client)
    run = (
        await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json={"run_type": "sweep_pull"})
    ).json()
    service = dyno_app.state.dyno_service
    rt = service.runtime(sid)
    async with rt.stream.subscribe() as sub:
        await OutputRouter(service, rt)._worker_lost("teste")
        envelope = await asyncio.wait_for(sub.__anext__(), 5.0)
        while envelope["type"] != "error":
            envelope = await asyncio.wait_for(sub.__anext__(), 5.0)
    assert envelope["payload"]["code"] == "SIM_WORKER_UNAVAILABLE" and envelope["payload"]["fatal"]
    stored = (await dyno_client.get(f"/api/v1/runs/{run['run_id']}")).json()
    assert stored["state"] == "aborted" and stored["abort_reason"] == "internal_error"
    refused = await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)
    assert refused.status_code == 503 and refused.json()["code"] == "SIM_WORKER_UNAVAILABLE"
    damage_port: DynoDamagePort = dyno_app.state.damage_port
    assert await damage_port.live_health(sid, False) is None
    with pytest.raises(Exception, match="indisponível"):
        await damage_port.restore_engine(sid, None)


async def test_ec04_run_kept_in_memory_when_database_fails(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await new_session(dyno_client)
    repo = dyno_app.state.dyno_service.repo
    run = (await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)).json()

    async def broken(_run: Any) -> bool:
        return False

    monkeypatch.setattr(repo, "save_run", broken)
    done = await wait_terminal(dyno_client, run["run_id"])
    assert done["state"] == "completed"
    assert done["persisted"] is False


class _BrokenMaker:
    def __call__(self) -> Any:
        raise OperationalError("SELECT 1", {}, Exception("banco fora"))


async def test_repository_retries_and_degrades() -> None:
    repo = DynoRepository(_BrokenMaker(), retry_delays_s=(0.0, 0.0, 0.0))  # type: ignore[arg-type]
    assert repo.available
    from dyno_helpers import RUN_ID, SESSION_ID

    from simremap.dyno.contracts import DynoRun, DynoRunRequest, RunState, RunType

    run = DynoRun(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        run_type=RunType.SWEEP_PULL,
        request=DynoRunRequest(run_type=RunType.SWEEP_PULL),
        state=RunState.ARMING,
        started_at_tick=0,
        calibration_id="x",
        calibration_hash="a" * 64,
        seed=1,
        sim_hz=1000,
    )
    assert await repo.save_run(run) is False
    assert await repo.get_run(RUN_ID) is None
    assert await repo.get_session(SESSION_ID) is None
    assert await repo.runs_of(SESSION_ID) == []
    assert await repo.close_stale_sessions() == 0
    none = DynoRepository(None)
    assert not none.available
    assert await none.save_run(run) is False
    assert await none.get_run(RUN_ID) is None
    assert await none.runs_of(SESSION_ID) == []
    assert await none.close_stale_sessions() == 0
    assert await none.get_session(SESSION_ID) is None


async def test_runs_of_session_listing(dyno_client: httpx.AsyncClient, dyno_app: FastAPI) -> None:
    sid = await new_session(dyno_client)
    run = (await dyno_client.post(f"/api/v1/sessions/{sid}/runs", json=SHORT)).json()
    await wait_terminal(dyno_client, run["run_id"])
    runs = await dyno_app.state.dyno_service.repo.runs_of(sid)
    assert [r.run_id for r in runs] == [run["run_id"]]


async def test_calibration_listener_receives_apply_and_swap(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    """Ouvinte oficial ``add_calibration_listener`` (auditoria V-03 sem troca de classe)."""
    from simremap.dyno.session import CalibrationApplied
    from simremap.ecu.session_port import CalibrationApplyCommand

    service = dyno_app.state.dyno_service
    seen: list[CalibrationApplied] = []

    def broken(event: CalibrationApplied) -> None:
        raise RuntimeError("ouvinte com defeito")

    remove = service.add_calibration_listener(seen.append)
    assert service.add_calibration_listener(seen.append) is not None  # idempotente
    service.add_calibration_listener(broken)
    sid = await new_session(dyno_client)
    rt = service.runtime(sid)
    cal = rt.calibration
    port: DynoEcuSessionPort = dyno_app.state.ecu_session_port
    applied = await port.apply_calibration(
        sid,
        CalibrationApplyCommand(
            request_id="apply-1",
            session_id=sid,
            calibration_id=cal.calibration_id,
            version=cal.version,
            content_hash=cal.content_hash,
            mode="full",
            payload_json=cal.content.model_dump_json(),
        ),
    )
    swap = EcuSwapCommand(
        request_id="swap-2",
        session_id=sid,
        profile_id="ft-pro",
        previous_profile_id="oem-stage",
        ecu_state="awaiting_base_setup",
    )
    await dyno_app.state.profiles_session_port.swap_ecu(sid, swap)  # sem calibração: sem evento
    assert [(e.kind, e.session_id, e.t_sim_s, e.content_hash) for e in seen] == [
        ("calibration.apply", sid, applied, cal.content_hash)
    ]
    assert type(dyno_app.state.ecu_session_port) is DynoEcuSessionPort  # classe do dono intacta
    remove()
    service.remove_calibration_listener(broken)
    assert seen.append not in service._calibration_listeners
    assert broken not in service._calibration_listeners


async def test_t031_session_exposes_active_calibration(
    dyno_client: httpx.AsyncClient, dyno_app: FastAPI
) -> None:
    """``calibration_id`` fica a inicial; ``active_calibration_*`` segue apply e swap."""
    from simremap.ecu.session_port import CalibrationApplyCommand

    service = dyno_app.state.dyno_service
    sid = await new_session(dyno_client)
    cal = service.runtime(sid).calibration
    created = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert created["active_calibration_id"] == cal.calibration_id == created["calibration_id"]
    assert created["active_calibration_version"] == cal.version
    await dyno_app.state.ecu_session_port.apply_calibration(
        sid,
        CalibrationApplyCommand(
            request_id="apply-t031",
            session_id=sid,
            calibration_id="cal-t031-applied",
            version=cal.version + 1,
            content_hash=cal.content_hash,
            mode="full",
            payload_json=cal.content.model_dump_json(),
        ),
    )
    applied = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert applied["calibration_id"] == cal.calibration_id
    assert applied["active_calibration_id"] == "cal-t031-applied"
    assert applied["active_calibration_version"] == cal.version + 1
    without_map = EcuSwapCommand(
        request_id="swap-t031-a",
        session_id=sid,
        profile_id="ft-pro",
        previous_profile_id="oem-stage",
        ecu_state="awaiting_base_setup",
    )
    await dyno_app.state.profiles_session_port.swap_ecu(sid, without_map)
    kept = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert kept["active_calibration_id"] == "cal-t031-applied"  # sem mapa: worker mantém
    with_map = EcuSwapCommand(
        request_id="swap-t031-b",
        session_id=sid,
        profile_id="ft-pro",
        previous_profile_id="ft-pro",
        ecu_state="standalone_ready",
        calibration_id="cal-t031-base",
        calibration_version=3,
        content_hash=cal.content_hash,
        calibration_payload_json=cal.content.model_dump_json(),
    )
    await dyno_app.state.profiles_session_port.swap_ecu(sid, with_map)
    swapped = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert swapped["calibration_id"] == cal.calibration_id
    assert (swapped["active_calibration_id"], swapped["active_calibration_version"]) == (
        "cal-t031-base",
        3,
    )
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    assert service.runtime(sid) is None  # encerrada: lida do banco
    stored = (await dyno_client.get(f"/api/v1/sessions/{sid}")).json()
    assert stored["state"] == "closed"
    assert stored["active_calibration_id"] == "cal-t031-base"
    assert stored["active_calibration_version"] == 3


async def test_t031_closed_session_health_without_runs_is_409(
    dyno_client: httpx.AsyncClient,
) -> None:
    """B3: encerrada sem puxadas (sem saúde gravada) ⇒ 409 ``SESSION_CLOSED``, não 503."""
    sid = await new_session(dyno_client)
    assert (await dyno_client.delete(f"/api/v1/sessions/{sid}")).status_code == 204
    resp = await dyno_client.get(f"/api/v1/sessions/{sid}/engine/health")
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "SESSION_CLOSED"
