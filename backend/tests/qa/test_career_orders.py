"""As 7 ordens da carreira são aceitas, executadas e liquidadas com pagamento (003 T022,
RF-16). Marcador ``e2e`` (≈ 25–60 s por ordem):
``uv run --frozen pytest -m e2e tests/qa/test_career_orders.py``.

App de produção em worker ``process`` (como ``test_scenarios_approvable``). Por ordem:

1. aceite ⇒ job ``accepted`` ligado à tentativa e à sessão; uma 2.ª ordem com o job aberto
   ⇒ 409 ``CAREER_JOB_ALREADY_OPEN``; liquidar antes do fim ⇒ 409
   ``CAREER_ATTEMPT_NOT_FINISHED``;
2. a sessão da tentativa recebe o acerto real do cenário (``qa_play``) e a submissão é
   aprovada;
3. liquidação logo depois da avaliação ⇒ ``paid`` com o pagamento da ordem e +5 de
   reputação; repetir a liquidação não muda nada.

Reputação mínima: com 50 o ``swap-standalone`` (60) dá 409 ``CAREER_REPUTATION_TOO_LOW``; o
teste da ordem prepara a reputação no banco. Quebra: motor destruído e tentativa
abandonada sem nenhum ``GET`` dela, ou motor restaurado e abandonado ⇒ ``engine_broken`` com
o custo do motor e −10 de reputação (regressão: antes saía ``abandoned`` sem custo).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlmodel import col

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_play import play
from qa_support import (
    API,
    Json,
    apply_calibration,
    failed_criteria,
    map_cells,
    new_player,
    open_client,
    real_app,
    replace_calibration,
    run_pull,
    wait_attempt_ready,
)

from simremap.career.service import load_orders
from simremap.db.models.career import CareerProfileRow

pytestmark = pytest.mark.e2e

CAREER: Final = f"{API}/career"
PAID_REPUTATION: Final = 5
BROKEN_REPUTATION: Final = -10
INITIAL_BALANCE: Final = 500_000
INITIAL_REPUTATION: Final = 50
ORDERS: Final = tuple(load_orders())
TORQUE_TABLES: Final = ("torque_request", "torque_limit", "torque_limit_gear")


@pytest.fixture
async def career(
    settings_factory: Callable[..., Any],
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = real_app(settings_factory(worker_mode="process"))
    async with open_client(app) as client:
        yield app, client


async def _player(client: httpx.AsyncClient, nickname: str) -> tuple[str, dict[str, str]]:
    headers = await new_player(client, nickname)
    return headers["X-Player-Profile-Id"], headers


async def _profile(client: httpx.AsyncClient, profile_id: str) -> Json:
    resp = await client.get(f"{CAREER}/profiles/{profile_id}")
    assert resp.status_code == 200, resp.text
    body: Json = resp.json()
    return body


async def _accept(client: httpx.AsyncClient, profile_id: str, order_id: str) -> httpx.Response:
    return await client.post(f"{CAREER}/profiles/{profile_id}/jobs", json={"order_id": order_id})


async def _settle(client: httpx.AsyncClient, job_id: str) -> httpx.Response:
    return await client.post(f"{CAREER}/jobs/{job_id}/settle")


async def _set_reputation(app: FastAPI, profile_id: str, reputation: int) -> None:
    async with app.state.sessionmaker() as db:
        await db.execute(
            update(CareerProfileRow)
            .where(col(CareerProfileRow.profile_id) == profile_id)
            .values(reputation=reputation)
        )
        await db.commit()


def _exaggerated(content: Json) -> None:
    """Pressão 280 kPa abs, +8° de avanço e limites de torque ×1,5 (jornada do Lucas)."""
    tables = content["tables"]
    for name in TORQUE_TABLES:
        table = tables[name]
        if table["dims"] == 3:
            map_cells(table, lambda _r, _k, v: 1.5 * v)
        else:
            table["values"] = [1.5 * v for v in table["values"]]
    map_cells(tables["oem_pressure_target"], lambda _r, _k, v: 280.0 if v >= 150.0 else v)
    map_cells(tables["ignition_base"], lambda _r, _k, v: v + 8.0)


# --------------------------------------------------------------------------- ordens


@pytest.mark.parametrize("order_id", ORDERS)
async def test_order_accept_execute_and_settle(
    career: tuple[FastAPI, httpx.AsyncClient], order_id: str
) -> None:
    app, client = career
    order = load_orders()[order_id]
    profile_id, headers = await _player(client, f"qa_{order_id.replace('-', '_')}"[:24])
    await _profile(client, profile_id)
    await _set_reputation(app, profile_id, max(INITIAL_REPUTATION, order.min_reputation))
    before = await _profile(client, profile_id)

    accepted = await _accept(client, profile_id, order_id)
    assert accepted.status_code == 201, accepted.text
    job: Json = accepted.json()
    assert job["status"] == "accepted" and job["scenario_id"] == order.scenario_id
    other = next(o for o in ORDERS if o != order_id)
    assert (await _accept(client, profile_id, other)).json()["code"] == "CAREER_JOB_ALREADY_OPEN"
    early = await _settle(client, job["job_id"])
    assert early.status_code == 409 and early.json()["code"] == "CAREER_ATTEMPT_NOT_FINISHED"
    attempt = await wait_attempt_ready(client, job["attempt_id"], headers)
    assert attempt["session_id"] == job["session_id"]

    evaluation = await play(client, order.scenario_id, attempt, headers)
    assert evaluation["passed"] is True, failed_criteria(evaluation)
    settled = await _settle(client, job["job_id"])

    assert settled.status_code == 200, settled.text
    body = settled.json()
    assert body["status"] == "paid"
    assert body["delta_balance_brl"] == order.payout_brl
    assert body["delta_reputation"] == PAID_REPUTATION
    after = await _profile(client, profile_id)
    assert after["balance_brl"] == before["balance_brl"] + order.payout_brl
    assert after["reputation"] == before["reputation"] + PAID_REPUTATION
    again = await _settle(client, job["job_id"])
    assert again.json() == body


# --------------------------------------------------------------------------- reputação


async def test_minimum_reputation_is_enforced(career: tuple[FastAPI, httpx.AsyncClient]) -> None:
    _app, client = career
    profile_id, _headers = await _player(client, "qa_reputacao_baixa")
    swap = load_orders()["swap-standalone"]

    resp = await _accept(client, profile_id, swap.order_id)

    assert resp.status_code == 409, resp.text
    problem = resp.json()
    assert problem["code"] == "CAREER_REPUTATION_TOO_LOW"
    assert (problem["min_reputation"], problem["reputation"]) == (
        swap.min_reputation,
        INITIAL_REPUTATION,
    )
    assert (await client.get(f"{CAREER}/profiles/{profile_id}/jobs")).json() == []


# --------------------------------------------------------------------------- quebra


async def _broken_engine_settlement(
    client: httpx.AsyncClient, nickname: str, *, destroy: bool
) -> tuple[Json, Json]:
    """Aceita o Stage 1, quebra (ou só restaura) o motor e abandona sem ler a tentativa."""
    profile_id, headers = await _player(client, nickname)
    job = (await _accept(client, profile_id, "stage1-diario-seguro")).json()
    attempt = await wait_attempt_ready(client, job["attempt_id"], headers)
    session_id = attempt["session_id"]
    if destroy:
        await replace_calibration(client, attempt["calibration_id"], _exaggerated, "exagerada")
        await apply_calibration(client, session_id, attempt["calibration_id"])
        run = await run_pull(client, session_id, ramp_rate_rpm_s=150.0)
        assert run["state"] == "engine_failed", run.get("abort_reason")
    else:
        restored = await client.post(f"{API}/sessions/{session_id}/engine/restore")
        assert restored.status_code == 200, restored.text
    abandoned = await client.post(f"{API}/attempts/{job['attempt_id']}/abandon", headers=headers)
    assert abandoned.status_code == 200, abandoned.text
    settled = await _settle(client, job["job_id"])
    assert settled.status_code == 200, settled.text
    return settled.json(), await _profile(client, profile_id)


@pytest.mark.parametrize("destroy", [True, False], ids=["engine_failed", "restored"])
async def test_broken_engine_charges_engine_cost(
    career: tuple[FastAPI, httpx.AsyncClient], destroy: bool
) -> None:
    _app, client = career
    stage1 = load_orders()["stage1-diario-seguro"]

    job, profile = await _broken_engine_settlement(client, f"qa_quebra_{destroy}", destroy=destroy)

    assert job["status"] == "engine_broken"
    assert job["delta_balance_brl"] == -stage1.engine_cost_brl
    assert job["delta_reputation"] == BROKEN_REPUTATION
    assert profile["balance_brl"] == INITIAL_BALANCE - stage1.engine_cost_brl
    assert profile["reputation"] == INITIAL_REPUTATION + BROKEN_REPUTATION
