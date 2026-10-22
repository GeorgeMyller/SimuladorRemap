"""API do Modo Carreira (002 T043; RF-25, RN-07; interfaces/career.md).

Aceite cria a tentativa; liquidação aprovada credita o pagamento, reprovada só tira
reputação, motor quebrado debita o custo do motor; liquidação idempotente; reputação baixa,
job aberto e tentativa em andamento dão 409 em ``application/problem+json``.
"""

from __future__ import annotations

from typing import Any

from scn_env import ScnEnv
from scn_helpers import RunSpec

from simremap.career.contracts import INITIAL_BALANCE_BRL, INITIAL_REPUTATION, JobStatus
from simremap.career.service import REPUTATION_CHANGE, load_orders
from simremap.catalog.trademarks import find_trademarks
from simremap.dyno.contracts import RunState
from simremap.scenarios.catalog import BUILTIN_IDS

GOOD = RunSpec(peak_whp=262.0, egt_max_c=930.0, knock_max_deg=1.5)
STAGE1 = "stage1-diario-seguro"
BASE = "/api/v1/career"


async def _player(car: ScnEnv, nickname: str = "oficina_lu") -> tuple[str, dict[str, str]]:
    headers = await car.profile(nickname)
    return headers["X-Player-Profile-Id"], headers


async def _accept(car: ScnEnv, profile_id: str, order_id: str = STAGE1) -> dict[str, Any]:
    resp = await car.client.post(f"{BASE}/profiles/{profile_id}/jobs", json={"order_id": order_id})
    assert resp.status_code == 201, resp.text
    assert resp.headers["Location"] == f"{BASE}/jobs/{resp.json()['job_id']}"
    await car.drain()
    job: dict[str, Any] = resp.json()
    return job


async def _settle(car: ScnEnv, job_id: str) -> dict[str, Any]:
    resp = await car.client.post(f"{BASE}/jobs/{job_id}/settle")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


async def _profile(car: ScnEnv, profile_id: str) -> dict[str, Any]:
    resp = await car.client.get(f"{BASE}/profiles/{profile_id}")
    assert resp.status_code == 200, resp.text
    data: dict[str, Any] = resp.json()
    return data


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == code


# --------------------------------------------------------------------------- consulta


def test_orders_point_to_builtin_scenarios() -> None:
    orders = load_orders()
    assert len(orders) == 7
    assert {o.scenario_id for o in orders.values()} == set(BUILTIN_IDS)
    for order in orders.values():
        assert order.engine_cost_brl > order.payout_brl
        assert not find_trademarks(f"{order.title} {order.client} {order.briefing}")


async def test_orders_and_profile_created_on_first_read(car: ScnEnv) -> None:
    resp = await car.client.get(f"{BASE}/orders")
    assert resp.status_code == 200
    first = resp.json()[0]
    assert set(first) == {
        "order_id",
        "title",
        "client",
        "briefing",
        "scenario_id",
        "payout_brl",
        "engine_cost_brl",
        "min_reputation",
    }
    profile_id, _ = await _player(car)
    profile = await _profile(car, profile_id)
    assert profile["balance_brl"] == INITIAL_BALANCE_BRL == 500_000
    assert profile["reputation"] == INITIAL_REPUTATION == 50
    assert (await _profile(car, profile_id))["created_at"] == profile["created_at"]
    history = await car.client.get(f"{BASE}/profiles/{profile_id}/jobs")
    assert history.status_code == 200 and history.json() == []


async def test_unknown_profile_order_and_job(car: ScnEnv) -> None:
    missing = "00000000-0000-4000-8000-000000000000"
    _problem(await car.client.get(f"{BASE}/profiles/{missing}"), 404, "PLAYER_PROFILE_NOT_FOUND")
    profile_id, _ = await _player(car)
    resp = await car.client.post(
        f"{BASE}/profiles/{profile_id}/jobs", json={"order_id": "ordem-inexistente"}
    )
    _problem(resp, 404, "CAREER_ORDER_NOT_FOUND")
    _problem(await car.client.post(f"{BASE}/jobs/{missing}/settle"), 404, "CAREER_JOB_NOT_FOUND")
    bad = await car.client.post(f"{BASE}/profiles/{profile_id}/jobs", json={})
    _problem(bad, 422, "VALIDATION_FAILED")


# --------------------------------------------------------------------------- aceite


async def test_accept_creates_attempt_and_blocks_second_job(car: ScnEnv) -> None:
    profile_id, headers = await _player(car)
    job = await _accept(car, profile_id)
    assert job["status"] == "accepted" and job["scenario_id"] == "stage1-oem"
    assert job["payout_brl"] == 120_000 and job["engine_cost_brl"] == 900_000
    assert job["delta_balance_brl"] is None and job["settled_at"] is None
    attempt = await car.attempt(job["attempt_id"], headers)
    assert attempt["scenario_id"] == "stage1-oem"
    assert attempt["session_id"] == job["session_id"]
    assert attempt["state"] == "in_progress"
    again = await car.client.post(
        f"{BASE}/profiles/{profile_id}/jobs", json={"order_id": "diagnostico-bomba-combustivel"}
    )
    _problem(again, 409, "CAREER_JOB_ALREADY_OPEN")
    assert again.json()["job_id"] == job["job_id"]
    not_done = await car.client.post(f"{BASE}/jobs/{job['job_id']}/settle")
    _problem(not_done, 409, "CAREER_ATTEMPT_NOT_FINISHED")
    assert not_done.json()["state"] == "in_progress"


async def test_reputation_too_low(car: ScnEnv) -> None:
    profile_id, _ = await _player(car)
    resp = await car.client.post(
        f"{BASE}/profiles/{profile_id}/jobs", json={"order_id": "swap-standalone"}
    )
    _problem(resp, 409, "CAREER_REPUTATION_TOO_LOW")
    assert resp.json()["min_reputation"] == 60 and resp.json()["reputation"] == 50
    history = await car.client.get(f"{BASE}/profiles/{profile_id}/jobs")
    assert history.json() == []
    assert car.sim.active() == []


# --------------------------------------------------------------------------- liquidação


async def test_settle_passed_pays_and_is_idempotent(car: ScnEnv) -> None:
    profile_id, headers = await _player(car)
    job = await _accept(car, profile_id)
    attempt = await car.attempt(job["attempt_id"], headers)
    car.tune(attempt, GOOD)
    await car.pull(attempt)
    await car.pull(attempt)
    evaluation = await car.submit(attempt, headers)
    assert evaluation["passed"] is True
    settled = await _settle(car, job["job_id"])
    assert settled["status"] == "paid"
    assert settled["delta_balance_brl"] == 120_000
    assert settled["delta_reputation"] == REPUTATION_CHANGE[JobStatus.PAID] == 5
    assert settled["settled_at"] is not None
    assert await _settle(car, job["job_id"]) == settled
    profile = await _profile(car, profile_id)
    assert profile["balance_brl"] == 620_000 and profile["reputation"] == 55
    history = (await car.client.get(f"{BASE}/profiles/{profile_id}/jobs")).json()
    assert history == [settled]
    # Job liquidado libera nova ordem.
    await _accept(car, profile_id, "diagnostico-bomba-combustivel")


async def test_settle_failed_only_costs_reputation(car: ScnEnv) -> None:
    profile_id, _ = await _player(car)
    job = await _accept(car, profile_id)
    await car.services.repo.update_attempt(job["attempt_id"], state="failed_final")
    settled = await _settle(car, job["job_id"])
    assert settled["status"] == "failed"
    assert settled["delta_balance_brl"] == 0 and settled["delta_reputation"] == -5
    profile = await _profile(car, profile_id)
    assert profile["balance_brl"] == 500_000 and profile["reputation"] == 45


async def test_settle_abandoned(car: ScnEnv) -> None:
    profile_id, headers = await _player(car)
    job = await _accept(car, profile_id)
    resp = await car.client.post(f"/api/v1/attempts/{job['attempt_id']}/abandon", headers=headers)
    assert resp.status_code == 200
    settled = await _settle(car, job["job_id"])
    assert settled["status"] == "abandoned"
    assert settled["delta_balance_brl"] == 0 and settled["delta_reputation"] == -3


async def test_engine_broken_debits_engine_cost(car: ScnEnv) -> None:
    """RN-07: quebra debita o custo do motor; o saldo pode ficar negativo."""
    profile_id, headers = await _player(car)
    for _ in range(6):  # 6 quebras de R$ 9.000,00 a partir de R$ 5.000,00
        job = await _accept(car, profile_id)
        attempt = await car.attempt(job["attempt_id"], headers)
        car.sim.queue.append([RunSpec(state=RunState.ENGINE_FAILED, failure=True)])
        await car.pull(attempt)
        await car.attempt(job["attempt_id"], headers)  # classifica a puxada com a falha
        resp = await car.client.post(
            f"/api/v1/attempts/{job['attempt_id']}/abandon", headers=headers
        )
        assert resp.status_code == 200
        settled = await _settle(car, job["job_id"])
        assert settled["status"] == "engine_broken"
        assert settled["delta_balance_brl"] == -900_000
    profile = await _profile(car, profile_id)
    assert profile["balance_brl"] == 500_000 - 6 * 900_000
    assert profile["reputation"] == 0  # 50 - 6 x 10, limitado a 0
    history = (await car.client.get(f"{BASE}/profiles/{profile_id}/jobs")).json()
    assert [j["delta_reputation"] for j in history] == [0, -10, -10, -10, -10, -10]
    low = await car.client.post(
        f"{BASE}/profiles/{profile_id}/jobs", json={"order_id": "diagnostico-bomba-combustivel"}
    )
    _problem(low, 409, "CAREER_REPUTATION_TOO_LOW")


async def test_openapi_lists_career_routes(car: ScnEnv) -> None:
    spec = (await car.client.get("/openapi.json")).json()
    paths = {(m, p) for p, item in spec["paths"].items() for m in item if p.startswith(BASE)}
    assert paths == {
        ("get", f"{BASE}/orders"),
        ("get", f"{BASE}/profiles/{{profile_id}}"),
        ("get", f"{BASE}/profiles/{{profile_id}}/jobs"),
        ("post", f"{BASE}/profiles/{{profile_id}}/jobs"),
        ("post", f"{BASE}/jobs/{{job_id}}/settle"),
    }
    settle = spec["paths"][f"{BASE}/jobs/{{job_id}}/settle"]["post"]
    assert "CAREER_ATTEMPT_NOT_FINISHED" in settle["x-error-codes"]
