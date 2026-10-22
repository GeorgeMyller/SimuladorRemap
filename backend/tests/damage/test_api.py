"""Endpoints E-12 a E-14 do dano com uma porta de sessões falsa (T136; RF-20, RF-21, RF-27;
EC-07 a EC-10, EC-13).

O ``dyno-bench`` ainda não existe: as sessões e puxadas vêm do ``InProcessDamagePort``
publicado em ``app.state.damage_port`` e as linhas ``simulation_session``/``dyno_run`` são
inseridas direto no banco para satisfazer as FKs ``RESTRICT``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from kfm_helpers import (
    RUN,
    SESSION,
    SHA,
    ModelFactory,
    dyno_run,
    lucas_report,
    make_state,
    run_lucas,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from simremap.damage.contracts import ForensicReport
from simremap.damage.model import DamageModel
from simremap.damage.service import ForensicService
from simremap.damage.session_port import InProcessDamagePort, SessionView
from simremap.db.models.damage import EngineHealthRow, FailureEventRow, ForensicReportRow
from simremap.db.models.dyno import DynoRunRow, SimulationSessionRow

OTHER_RUN = "01JAB0000000000000000000EE"


@dataclass
class Env:
    app: FastAPI
    client: httpx.AsyncClient
    port: InProcessDamagePort
    service: ForensicService
    model: DamageModel
    maker: async_sessionmaker[AsyncSession]


async def _insert_rows(maker: async_sessionmaker[AsyncSession], *run_ids: str) -> None:
    async with maker() as session:
        session.add(
            SimulationSessionRow(
                session_id=SESSION,
                vehicle_id="hatch-20t-gdi",
                data_version=1,
                catalog_sha256=SHA,
                calibration_id="cal-lucas",
                fuel_id="e27",
                seed=42,
                config_json={"damage_enabled": True},
            )
        )
        await session.flush()
        for run_id in run_ids:
            session.add(
                DynoRunRow(
                    run_id=run_id,
                    session_id=SESSION,
                    run_type="sweep_pull",
                    state="engine_failed",
                    calibration_id="cal-lucas",
                    calibration_hash=SHA,
                    request_json={"run_type": "sweep_pull"},
                    started_at_tick=0,
                )
            )
        await session.commit()


@pytest.fixture
async def env(app: FastAPI, client: httpx.AsyncClient, make_model: ModelFactory) -> Env:
    maker: async_sessionmaker[AsyncSession] = app.state.sessionmaker
    await _insert_rows(maker, RUN)
    port = InProcessDamagePort()
    model = make_model()
    port.register_session(SessionView(SESSION, "hatch-20t-gdi", "ready"), model)
    port.register_run(dyno_run())
    service = ForensicService(maker, retry_delays_s=(0.0, 0.0, 0.0))
    app.state.damage_port = port
    app.state.forensic_service = service
    return Env(app, client, port, service, model, maker)


def _problem(resp: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = resp.json()
    assert body["code"] == code
    return body


class TestEngineHealth:
    async def test_new_session_is_intact(self, env: Env) -> None:
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["components"]) == 15
        assert body["integrity_pct"] == 100.0 and body["intact"] is True
        assert body["engine_locked"] is False and body["failures"] == []
        assert len(resp.content) <= 8 * 1024

    async def test_unknown_session(self, env: Env) -> None:
        resp = await env.client.get(
            "/api/v1/sessions/ffffffffffffffffffffffffffffffff/engine/health"
        )
        _problem(resp, 404, "SESSION_NOT_FOUND")

    async def test_locked_engine_and_failures_filter(self, env: Env) -> None:
        env.model.step(make_state(1, 0.001, 0.0, turbo_rpm=240_000.0), 0.001)
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        body = resp.json()
        assert body["engine_locked"] is True and body["intact"] is False
        assert body["failures"][0]["mode"] == "turbo_meltdown"
        resp = await env.client.get(
            f"/api/v1/sessions/{SESSION}/engine/health", params={"include_failures": "false"}
        )
        assert resp.json()["failures"] == []

    async def test_dead_worker_returns_persisted_state(self, env: Env) -> None:
        env.model.step(make_state(1, 0.001, 0.0, turbo_rpm=240_000.0), 0.001)
        await env.service.persist_failures(env.model.failures)
        await env.service.persist_engine_health(env.model.engine_health(), env.model.rod_weights, 1)
        env.port.detach_worker(SESSION)
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["engine_locked"] is True
        assert [f["component_id"] for f in body["failures"]] == ["turbo:turbine"]

    async def test_dead_worker_without_persisted_state(self, env: Env) -> None:
        env.port.detach_worker(SESSION)
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        _problem(resp, 503, "SIM_WORKER_UNAVAILABLE")

    async def test_closed_session_without_persisted_state(self, env: Env) -> None:
        """T031 (B3): sessão encerrada sem puxadas ⇒ 409 ``SESSION_CLOSED``, não 503."""
        env.port.update_session(SESSION, state="closed")
        env.port.detach_worker(SESSION)
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        _problem(resp, 409, "SESSION_CLOSED")

    async def test_closed_session_returns_persisted_state(self, env: Env) -> None:
        await env.service.persist_engine_health(env.model.engine_health(), env.model.rod_weights, 1)
        env.port.update_session(SESSION, state="closed")
        env.port.detach_worker(SESSION)
        resp = await env.client.get(f"/api/v1/sessions/{SESSION}/engine/health")
        assert resp.status_code == 200, resp.text
        assert resp.json()["intact"] is True


class TestRestore:
    async def test_restore_after_failure(self, env: Env) -> None:
        env.model.step(make_state(1, 0.001, 0.0, turbo_rpm=240_000.0), 0.001)
        env.port.update_session(SESSION, state="engine_locked")
        resp = await env.client.post(
            f"/api/v1/sessions/{SESSION}/engine/restore", json={"note": "troca do turbo"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["intact"] is True and body["engine_locked"] is False
        assert body["restore_count"] == 1
        assert (await env.port.get_session(SESSION)).state == "ready"  # type: ignore[union-attr]
        async with env.maker() as session:
            row = await session.get(EngineHealthRow, SESSION)
        assert row is not None and row.restore_count == 1 and not row.engine_locked
        assert len(row.rod_weights_json) == 4

    async def test_restore_is_idempotent_on_health(self, env: Env) -> None:
        for expected in (1, 2):
            resp = await env.client.post(f"/api/v1/sessions/{SESSION}/engine/restore")
            assert resp.status_code == 200
            assert resp.json()["restore_count"] == expected

    async def test_restore_conflicts(self, env: Env) -> None:
        env.port.update_session(SESSION, active_run_id=RUN)
        resp = await env.client.post(f"/api/v1/sessions/{SESSION}/engine/restore")
        _problem(resp, 409, "RUN_IN_PROGRESS")
        env.port.update_session(SESSION, active_run_id=None, state="closed")
        resp = await env.client.post(f"/api/v1/sessions/{SESSION}/engine/restore")
        _problem(resp, 409, "SESSION_CLOSED")

    async def test_restore_unknown_session_and_dead_worker(self, env: Env) -> None:
        resp = await env.client.post(
            "/api/v1/sessions/ffffffffffffffffffffffffffffffff/engine/restore"
        )
        _problem(resp, 404, "SESSION_NOT_FOUND")
        env.port.detach_worker(SESSION)
        resp = await env.client.post(f"/api/v1/sessions/{SESSION}/engine/restore")
        _problem(resp, 503, "SIM_WORKER_UNAVAILABLE")

    async def test_note_is_limited(self, env: Env) -> None:
        resp = await env.client.post(
            f"/api/v1/sessions/{SESSION}/engine/restore", json={"note": "x" * 121}
        )
        _problem(resp, 422, "VALIDATION_FAILED")


class TestForensicReport:
    async def _failed_model(self, env: Env) -> DamageModel:
        run_lucas(env.model)
        assert env.model.engine_locked
        return env.model

    async def test_report_ready_within_500_ms(self, env: Env) -> None:
        model = await self._failed_model(env)
        start = time.perf_counter()
        task = env.service.submit(model.freeze_trace(), dyno_run())
        while True:
            resp = await env.client.get(f"/api/v1/runs/{RUN}/forensic-report")
            if resp.status_code != 409:
                break
            await asyncio.sleep(0.01)
        elapsed = time.perf_counter() - start
        await task
        assert resp.status_code == 200, resp.text
        assert elapsed <= 0.5
        assert "X-Simremap-Persisted" not in resp.headers
        report = ForensicReport.model_validate(resp.json())
        assert report.report_kind == "failure" and set(report.texts) == {
            "beginner",
            "intermediate",
            "instructor",
        }
        async with env.maker() as session:
            rows = (await session.execute(select(ForensicReportRow))).scalars().all()
            events = (await session.execute(select(FailureEventRow))).scalars().all()
        assert [r.report_sha256 for r in rows] == [report.report_sha256]
        assert [e.failure_event_id for e in events] == [report.failure_event.failure_event_id]  # type: ignore[union-attr]

    async def test_generation_p95_under_500_ms(self, env: Env) -> None:
        model = await self._failed_model(env)
        trace = model.freeze_trace()
        service = ForensicService(None)
        durations = []
        for _ in range(20):
            start = time.perf_counter()
            await service.generate(trace, dyno_run())
            durations.append(time.perf_counter() - start)
        durations.sort()
        assert durations[18] <= 0.5

    async def test_pending_returns_409_with_retry_after(self, env: Env) -> None:
        model = await self._failed_model(env)
        release = threading.Event()
        real = env.service._builder

        def slow(*args: Any, **kwargs: Any) -> ForensicReport:
            release.wait(5.0)
            return real(*args, **kwargs)

        env.service._builder = slow
        task = env.service.submit(model.freeze_trace(), dyno_run())
        await asyncio.sleep(0)
        resp = await env.client.get(f"/api/v1/runs/{RUN}/forensic-report")
        _problem(resp, 409, "FORENSIC_REPORT_PENDING")
        assert resp.headers["Retry-After"] == "1"
        release.set()
        await task
        resp = await env.client.get(f"/api/v1/runs/{RUN}/forensic-report")
        assert resp.status_code == 200

    async def test_timeout_falls_back_to_minimal_report(self, env: Env) -> None:
        model = await self._failed_model(env)
        release = threading.Event()

        def stuck(*_args: Any, **_kwargs: Any) -> ForensicReport:
            release.wait(5.0)
            raise RuntimeError("não deveria ser usado")

        service = ForensicService(None, timeout_s=0.05, builder=stuck)
        report = await service.generate(model.freeze_trace(), dyno_run())
        release.set()
        assert len(report.causal_chain) == 1
        assert report.causal_chain[0].kind == "failure"
        assert (await service.get_report(RUN))[1] is False

    async def test_audience_filter_and_validation(self, env: Env) -> None:
        model = await self._failed_model(env)
        await env.service.generate(model.freeze_trace(), dyno_run())
        resp = await env.client.get(
            f"/api/v1/runs/{RUN}/forensic-report", params={"audience": "beginner"}
        )
        assert resp.status_code == 200
        assert list(resp.json()["texts"]) == ["beginner"]
        resp = await env.client.get(
            f"/api/v1/runs/{RUN}/forensic-report", params={"audience": "aluno"}
        )
        _problem(resp, 422, "VALIDATION_FAILED")

    async def test_not_found_cases(self, env: Env) -> None:
        resp = await env.client.get(f"/api/v1/runs/{OTHER_RUN}/forensic-report")
        _problem(resp, 404, "RUN_NOT_FOUND")
        env.port.register_run(dyno_run(OTHER_RUN, "completed"))
        resp = await env.client.get(f"/api/v1/runs/{OTHER_RUN}/forensic-report")
        _problem(resp, 404, "FORENSIC_REPORT_NOT_FOUND")

    async def test_report_kept_in_memory_when_db_rejects(self, env: Env) -> None:
        # puxada sem linha em dyno_run: a FK RESTRICT recusa a gravação (EC-08)
        model = env.model
        run_lucas(model, run_id=OTHER_RUN)
        env.port.register_run(dyno_run(OTHER_RUN))
        await env.service.generate(model.freeze_trace(), dyno_run(OTHER_RUN))
        resp = await env.client.get(f"/api/v1/runs/{OTHER_RUN}/forensic-report")
        assert resp.status_code == 200
        assert resp.headers["X-Simremap-Persisted"] == "false"

    async def test_report_served_from_database(self, env: Env) -> None:
        model = await self._failed_model(env)
        report = await env.service.generate(model.freeze_trace(), dyno_run())
        env.app.state.forensic_service = ForensicService(env.maker)
        resp = await env.client.get(f"/api/v1/runs/{RUN}/forensic-report")
        assert resp.status_code == 200
        assert resp.json()["report_sha256"] == report.report_sha256
        # regenerar a mesma puxada substitui a linha (UNIQUE run_id)
        await env.service.generate(model.freeze_trace(), dyno_run())
        async with env.maker() as session:
            rows = (await session.execute(select(ForensicReportRow))).scalars().all()
        assert len(rows) == 1

    async def test_memory_limit_per_session(self, env: Env) -> None:
        model = await self._failed_model(env)
        service = ForensicService(None, max_per_session=2)
        trace = model.freeze_trace()
        ids = ["01JAB00000000000000000000" + c for c in "FGH"]
        for run_id in ids:
            await service.generate(trace, dyno_run(run_id), kind="near_miss")
        with pytest.raises(Exception, match="laudo"):
            await service.get_report(ids[0])
        assert (await service.get_report(ids[2]))[0].run_id == ids[2]


async def test_router_without_port_has_no_sessions(app: FastAPI, client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/v1/sessions/{SESSION}/engine/health")
    _problem(resp, 404, "SESSION_NOT_FOUND")
    resp = await client.get(f"/api/v1/runs/{RUN}/forensic-report")
    _problem(resp, 404, "RUN_NOT_FOUND")


async def test_lucas_report_helper_matches_service(env: Env) -> None:
    run_lucas(env.model)
    direct = lucas_report(env.model)
    served = await env.service.generate(env.model.freeze_trace(), dyno_run())
    assert direct.report_sha256 == served.report_sha256
