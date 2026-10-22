"""Ajudantes da QA via API real (003 T020–T022; RF-12 a RF-16).

Módulo importável (sem ``conftest.py`` novo): cada teste de ``tests/qa/`` põe esta pasta no
``sys.path`` e importa ``qa_support``. A app é a de produção (catálogo real, ecu-core
semeado, ``ProfiledEcu``, dano padrão, telemetria a 1 kHz) em worker ``process`` com
``steps_per_tick = 10`` para as puxadas correrem mais rápido que o tempo real (não muda os
resultados, dyno RF-23).

- ``real_app``/``open_client``: app e ``httpx.AsyncClient`` com lifespan ativo;
- ``run_pull``: inicia uma puxada e espera o estado terminal e o log;
- ``new_player``/``start_attempt``/``submit``: perfil de jogador, tentativa em
  ``in_progress`` e submissão até a avaliação terminar;
- ``replace_calibration``/``apply_calibration``: nova versão no ecu-core e aplicação à sessão;
- ``interp`` e ``map_cells``: edição de tabelas por rotação e MAP.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, Final

import httpx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.api.main import create_app
from simremap.core.config import Settings

API: Final = "/api/v1"
TIMEOUT_S: Final = 300.0
TERMINAL_RUN: Final = frozenset({"completed", "aborted", "engine_failed"})
STEPS_PER_TICK: Final = 10

Json = dict[str, Any]


# --------------------------------------------------------------------------- app


def real_app(settings: Settings) -> FastAPI:
    app = create_app(settings)
    app.state.dyno_task_options = {"steps_per_tick": STEPS_PER_TICK}
    return app


@asynccontextmanager
async def open_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=120.0
        ) as client:
            yield client


# --------------------------------------------------------------------------- espera


async def poll(
    client: httpx.AsyncClient,
    url: str,
    done: Callable[[Json], bool],
    headers: dict[str, str] | None = None,
    timeout_s: float = TIMEOUT_S,
) -> Json:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        resp = await client.get(url, headers=headers or {})
        assert resp.status_code == 200, resp.text
        body: Json = resp.json()
        if done(body):
            return body
        await asyncio.sleep(0.2)
    raise AssertionError(f"tempo esgotado em {url}")


async def wait_run(client: httpx.AsyncClient, run_id: str) -> Json:
    run = await poll(client, f"{API}/runs/{run_id}", lambda b: b["state"] in TERMINAL_RUN)
    for _ in range(50):  # o log fica pronto até 2 s depois do estado terminal
        if (await client.get(f"{API}/runs/{run_id}/log")).status_code == 200:
            break
        await asyncio.sleep(0.1)
    return run


async def start_run(client: httpx.AsyncClient, session_id: str, **request: Any) -> str:
    resp = await client.post(f"{API}/sessions/{session_id}/runs", json=request)
    assert resp.status_code == 202, resp.text
    return str(resp.json()["run_id"])


async def run_pull(client: httpx.AsyncClient, session_id: str, **request: Any) -> Json:
    request.setdefault("run_type", "sweep_pull")
    return await wait_run(client, await start_run(client, session_id, **request))


# --------------------------------------------------------------------------- sessão


async def create_session(client: httpx.AsyncClient, **body: Any) -> Json:
    resp = await client.post(f"{API}/sessions", json={"seed": 42, **body})
    assert resp.status_code == 201, resp.text
    session: Json = resp.json()
    return session


async def close_session(client: httpx.AsyncClient, session_id: str) -> None:
    resp = await client.delete(f"{API}/sessions/{session_id}")
    assert resp.status_code == 204, resp.text


async def get_calibration(client: httpx.AsyncClient, calibration_id: str) -> Json:
    resp = await client.get(f"{API}/calibrations/{calibration_id}")
    assert resp.status_code == 200, resp.text
    cal: Json = resp.json()
    return cal


async def replace_calibration(
    client: httpx.AsyncClient,
    calibration_id: str,
    edit: Callable[[Json], None],
    summary: str = "QA",
) -> Json:
    """Nova versão do ``calibration_id``: ``edit`` muda uma cópia do conteúdo atual."""
    cal = await get_calibration(client, calibration_id)
    content: Json = copy.deepcopy(
        {k: cal[k] for k in ("fuel_model", "tables", "strategies", "profile_params")}
    )
    edit(content)
    body = {
        "base_version": cal["version"],
        **content,
        "metadata": {**cal["metadata"], "change_summary": summary},
    }
    resp = await client.put(f"{API}/calibrations/{calibration_id}", json=body)
    assert resp.status_code == 200, resp.text
    updated: Json = resp.json()
    return updated


async def apply_calibration(
    client: httpx.AsyncClient, session_id: str, calibration_id: str
) -> Json:
    resp = await client.post(
        f"{API}/sessions/{session_id}/calibration",
        json={"calibration_id": calibration_id, "profile_options": {"auto_fix_checksum": True}},
    )
    assert resp.status_code == 200, resp.text
    applied: Json = resp.json()
    return applied


# --------------------------------------------------------------------------- tentativas


async def new_player(client: httpx.AsyncClient, nickname: str) -> dict[str, str]:
    resp = await client.post(f"{API}/profiles", json={"nickname": nickname})
    assert resp.status_code == 201, resp.text
    return {"X-Player-Profile-Id": str(resp.json()["profile_id"])}


async def wait_attempt_ready(
    client: httpx.AsyncClient, attempt_id: str, headers: dict[str, str]
) -> Json:
    attempt = await poll(
        client, f"{API}/attempts/{attempt_id}", lambda b: b["state"] != "preparing", headers
    )
    assert attempt["state"] == "in_progress", attempt
    return attempt


async def start_attempt(
    client: httpx.AsyncClient, scenario_id: str, headers: dict[str, str]
) -> Json:
    resp = await client.post(f"{API}/scenarios/{scenario_id}/attempts", headers=headers)
    assert resp.status_code == 201, resp.text
    return await wait_attempt_ready(client, str(resp.json()["attempt_id"]), headers)


async def submit(
    client: httpx.AsyncClient,
    attempt_id: str,
    headers: dict[str, str],
    calibration_id: str,
    declared_defect: str | None = None,
) -> Json:
    url = f"{API}/attempts/{attempt_id}"
    body: Json = {"calibration_id": calibration_id}
    if declared_defect is not None:
        body["declared_defect"] = declared_defect
    resp = await client.post(f"{url}/submit", headers=headers, json=body)
    assert resp.status_code == 202, resp.text
    return await poll(client, f"{url}/evaluation", lambda b: b["status"] != "pending", headers)


def failed_criteria(evaluation: Json) -> dict[str, Any]:
    return {r["criterion_id"]: r["measured"] for r in evaluation["results"] if not r["passed"]}


# --------------------------------------------------------------------------- tabelas


def interp(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if x <= xs[0]:
        return float(ys[0])
    for (x0, y0), (x1, y1) in itertools.pairwise(zip(xs, ys, strict=True)):
        if x <= x1:
            return float(y0 + (x - x0) / (x1 - x0) * (y1 - y0))
    return float(ys[-1])


def map_cells(table: Json, cell: Callable[[float, float, float], float]) -> None:
    """Aplica ``cell(rpm, map_kpa, valor)`` a cada célula de uma tabela 3D rpm × MAP."""
    xs, ys = table["x"]["values"], table["y"]["values"]
    table["values"] = [
        [cell(r, kpa, v) for r, v in zip(xs, row, strict=True)]
        for kpa, row in zip(ys, table["values"], strict=True)
    ]
