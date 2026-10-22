"""Abandono logo após o início, com a ``baseline_pull`` em curso (porta real; bug 002).

App completa (catálogo real, ecu-core semeado, dyno-bench em worker ``process``). O
``POST /attempts/{id}/abandon`` fecha a sessão enquanto a baseline em fundo recebe a puxada
abortada e também tenta fechar a mesma sessão. Antes da correção o segundo fecho chegava ao
``del self._sessions[...]`` já feito pelo primeiro: 500 com ``KeyError``.

1. o abandono responde 200 com ``abandoned`` e a sessão fica ``closed``;
2. a baseline termina sem erro e não reescreve o estado (continua ``abandoned``);
3. dois ``delete_session`` concorrentes no ``DynoService`` fecham a sessão uma só vez.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.api.main import create_app
from simremap.core.errors import SimRemapError
from simremap.dyno.session import DynoService

SCENARIO_ID = "stage1-oem"


@pytest.fixture
async def real(settings_factory: Callable[..., Any]) -> AsyncIterator[tuple[FastAPI, Any]]:
    app = create_app(settings_factory(worker_mode="process"))
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield app, client


async def _start(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, str]]:
    created = await client.post("/api/v1/profiles", json={"nickname": "abandono_rapido"})
    assert created.status_code == 201, created.text
    headers = {"X-Player-Profile-Id": created.json()["profile_id"]}
    started = await client.post(f"/api/v1/scenarios/{SCENARIO_ID}/attempts", headers=headers)
    assert started.status_code == 201, started.text
    body: dict[str, Any] = started.json()
    return body, headers


async def _wait_baseline_running(app: FastAPI, session_id: str) -> None:
    dyno = app.state.dyno_service
    for _ in range(400):
        rt = dyno.runtime(session_id)
        if rt is not None and rt.view.active_run_id is not None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("a baseline não arrancou")


async def test_abandon_right_after_start_is_idempotent(real: tuple[FastAPI, Any]) -> None:
    app, client = real
    attempt, headers = await _start(client)
    session_id = attempt["session_id"]
    await _wait_baseline_running(app, session_id)

    resp = await client.post(f"/api/v1/attempts/{attempt['attempt_id']}/abandon", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "abandoned"
    await app.state.scenarios.attempts.drain()
    after = await client.get(f"/api/v1/attempts/{attempt['attempt_id']}", headers=headers)
    assert after.json()["state"] == "abandoned"
    assert app.state.dyno_service.runtime(session_id) is None
    closed = await client.get(f"/api/v1/sessions/{session_id}")
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "closed"


async def test_concurrent_delete_session_closes_once(real: tuple[FastAPI, Any]) -> None:
    app, client = real
    attempt, _headers = await _start(client)
    session_id = attempt["session_id"]
    await _wait_baseline_running(app, session_id)
    dyno: DynoService = app.state.dyno_service

    first, second = await asyncio.gather(
        dyno.delete_session(session_id), dyno.delete_session(session_id), return_exceptions=True
    )

    assert first is None, first
    assert second is None, second
    assert dyno.runtime(session_id) is None
    with pytest.raises(SimRemapError) as late:
        await dyno.delete_session(session_id)
    assert late.value.error_code == "SESSION_NOT_FOUND"
    await app.state.scenarios.attempts.drain()
