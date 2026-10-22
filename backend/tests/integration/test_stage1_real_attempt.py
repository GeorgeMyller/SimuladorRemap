"""Tentativa real do ``stage1-oem`` no ``hatch-20t-gdi`` (G-02; jornada do Lucas; T392/T388).

App completa (catálogo real, ecu-core com a calibração de série semeada, ecu-profiles com
o ``ProfiledEcu`` OEM-Stage, dyno-bench em worker ``process``, telemetria com o log a 1 kHz e
dano padrão), só com ``steps_per_tick = 10`` para a puxada correr mais rápido que o tempo
real (não muda os resultados, dyno RF-23):

1. perfil ``lucas_turbo`` inicia a tentativa: cópia da série + ``baseline_pull`` 2000 → 6300
   rpm em 4.ª ⇒ ``in_progress`` com ``baseline_peak_whp``;
2. a calibração da tentativa ganha uma versão "Stage 1" (``stage1_tables``) e é aplicada à
   sessão; 2 ``sweep_pull`` reais;
3. submissão ⇒ avaliação concluída com o ``evaluation_sha256`` estável, as puxadas de
   evidência ligadas ao log real e **todos** os critérios aprovados, incluindo o
   ``min_delta_whp`` de +40 whp (G-02).

Com o turbo classe IS20 recalibrado (gain-calibration) o Stage 1 a ~1,6 bar relativos dá
~+45 whp sem knock, com EGT ≤ 950 °C, lambda 0,80–0,995 e o motor intacto.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from simremap.api.main import create_app

TIMEOUT_S = 240.0


@pytest.fixture
def real_app(settings_factory: Callable[..., Any]) -> FastAPI:
    app = create_app(settings_factory(worker_mode="process"))
    app.state.dyno_task_options = {"steps_per_tick": 10}
    return app


@pytest.fixture
async def real_client(real_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(real_app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as c:
            yield c


async def poll(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    done: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + TIMEOUT_S
    while loop.time() < deadline:
        resp = await client.get(url, headers=headers)
        assert resp.status_code == 200, resp.text
        body: dict[str, Any] = resp.json()
        if done(body):
            return body
        await asyncio.sleep(0.25)
    raise AssertionError(f"tempo esgotado em {url}")


async def run_pull(client: httpx.AsyncClient, session_id: str, **request: Any) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/sessions/{session_id}/runs", json={"run_type": "sweep_pull", **request}
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]
    run = await poll(
        client,
        f"/api/v1/runs/{run_id}",
        {},
        lambda b: b["state"] in ("completed", "aborted", "engine_failed"),
    )
    for _ in range(40):  # o log fica pronto até 2 s depois do estado terminal
        if (await client.get(f"/api/v1/runs/{run_id}/log")).status_code == 200:
            break
        await asyncio.sleep(0.1)
    return run


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    for (x0, y0), (x1, y1) in itertools.pairwise(zip(xs, ys, strict=True)):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return ys[-1]


# Stage 1: teto da pressão alvo por rotação (kPa abs). A pressão de série cai de 222 kPa
# (5000 rpm) para 198 kPa (6500 rpm); o remap segura ~1,6 bar relativos no topo e fica mais
# baixo a 4500–5000 rpm, onde o torque na biela (≤ 420 N·m, PRD) é o limite.
STAGE1_BOOST_RPM = [4000.0, 4500.0, 5000.0, 5500.0, 6500.0]
STAGE1_BOOST_KPA = [232.0, 236.0, 244.0, 252.0, 262.0]
STAGE1_TORQUE_NM = 430.0  # limites de torque da ECU acima de 5250 rpm (a pressão limita antes)
STAGE1_OVERBOOST_KPA = 300.0


def stage1_tables(cal: dict[str, Any]) -> dict[str, Any]:
    """Stage 1 "legítimo" no OEM-Stage (sem tocar em hardware nem nas proteções).

    - ``torque_request`` ×1,2 e ``torque_limit_gear`` de 3.ª em diante a 430 N·m (de série
      385 N·m, que cortava o pedido antes da pressão);
    - ``torque_limit`` de série até 4250 rpm (bielas: 420 N·m / 52 kN), 400 N·m a 4750 rpm e
      430 N·m a partir de 5250 rpm;
    - ``oem_pressure_target`` limitado por ``STAGE1_BOOST_*`` (232 → 262 kPa abs);
    - ``lambda_target`` a plena carga (MAP ≥ 140 kPa) 0,86 a partir de 2900 rpm e 0,80 a partir
      de 4000 rpm (janela 0,75–0,90 do cenário e EGT pré-turbina ≤ 950 °C).
    O turbo fica abaixo de 230 000 rpm (máximo 250 000 rpm) e o avanço é o de série.
    """
    tables: dict[str, Any] = copy.deepcopy(cal["tables"])
    request = tables["torque_request"]
    request["values"] = [[1.2 * v for v in row] for row in request["values"]]
    gear = tables["torque_limit_gear"]
    gear["values"] = [
        max(v, STAGE1_TORQUE_NM) if g >= 3 else v
        for g, v in zip(gear["x"]["values"], gear["values"], strict=True)
    ]
    lim = tables["torque_limit"]
    lim["values"] = [
        max(v, _interp(r, [4250, 4750, 5250], [v, 400.0, STAGE1_TORQUE_NM])) if r >= 4250 else v
        for r, v in zip(lim["x"]["values"], lim["values"], strict=True)
    ]
    pressure = tables["oem_pressure_target"]
    pressure["values"] = [
        [
            min(v, _interp(r, STAGE1_BOOST_RPM, STAGE1_BOOST_KPA))
            for r, v in zip(pressure["x"]["values"], row, strict=True)
        ]
        for row in pressure["values"]
    ]
    lam = tables["lambda_target"]
    lam["values"] = [
        [
            (min(v, 0.80) if r >= 4000 else min(v, 0.86) if r >= 2900 else v) if kpa >= 140 else v
            for r, v in zip(lam["x"]["values"], row, strict=True)
        ]
        for kpa, row in zip(lam["y"]["values"], lam["values"], strict=True)
    ]
    return tables


def stage1_strategies(cal: dict[str, Any]) -> dict[str, Any]:
    """Overboost da ECU acima do novo alvo (de série 265 kPa)."""
    strategies: dict[str, Any] = copy.deepcopy(cal["strategies"])
    strategies["boost_control"]["overboost_kpa"] = STAGE1_OVERBOOST_KPA
    return strategies


async def test_stage1_oem_real_attempt(real_client: httpx.AsyncClient) -> None:
    client = real_client
    created = await client.post("/api/v1/profiles", json={"nickname": "lucas_turbo"})
    headers = {"X-Player-Profile-Id": created.json()["profile_id"]}
    started = await client.post("/api/v1/scenarios/stage1-oem/attempts", headers=headers)
    assert started.status_code == 201, started.text
    attempt = started.json()
    url = f"/api/v1/attempts/{attempt['attempt_id']}"
    attempt = await poll(client, url, headers, lambda b: b["state"] != "preparing")
    assert attempt["state"] == "in_progress", attempt
    baseline = attempt["baseline_peak_whp"]
    assert baseline is not None and baseline > 100.0
    sid = attempt["session_id"]
    cal_id = attempt["calibration_id"]

    cal = (await client.get(f"/api/v1/calibrations/{cal_id}")).json()
    replace = {
        "base_version": cal["version"],
        "fuel_model": cal["fuel_model"],
        "tables": stage1_tables(cal),
        "strategies": stage1_strategies(cal),
        "profile_params": cal["profile_params"],
        "metadata": {**cal["metadata"], "name": "Stage 1", "change_summary": "stage 1"},
    }
    put = await client.put(f"/api/v1/calibrations/{cal_id}", json=replace)
    assert put.status_code == 200, put.text
    applied = await client.post(
        f"/api/v1/sessions/{sid}/calibration",
        json={"calibration_id": cal_id, "profile_options": {"auto_fix_checksum": True}},
    )
    assert applied.status_code == 200, applied.text

    runs = [await run_pull(client, sid) for _ in range(2)]
    progress = await client.get(url, headers=headers)
    classified = {r["run_id"]: r for r in progress.json()["runs"]}
    for run in runs:
        assert run["run_id"] in classified
    submit = await client.post(f"{url}/submit", headers=headers, json={"calibration_id": cal_id})
    assert submit.status_code == 202, submit.text
    evaluation = await poll(
        client, f"{url}/evaluation", headers, lambda b: b["status"] != "pending"
    )
    assert evaluation["status"] == "completed", evaluation
    assert len(evaluation["evaluation_sha256"]) == 64
    egt = next(r for r in evaluation["results"] if r["kind"] == "max_egt_c")
    if egt["evidence"]:
        assert egt["evidence"][0]["channel"] == "egt_collector_c"
    results = {r["criterion_id"]: r for r in evaluation["results"]}
    failed = {cid: r["measured"] for cid, r in results.items() if not r["passed"]}
    # Tudo tem de aprovar: ganho, knock, EGT, janela de lambda, integridade (sem dano),
    # 2 puxadas válidas, dispersão e perfil final.
    assert not failed, failed
    delta = results["delta-whp"]["measured"]
    assert delta is not None and delta >= 40.0, (baseline, results["delta-whp"])
    assert evaluation["passed"] is True
