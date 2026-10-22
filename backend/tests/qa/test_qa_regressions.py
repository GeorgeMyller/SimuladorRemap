"""Regressões rápidas dos bugs achados na QA via API real (003 T020–T022).

App de produção em worker ``process`` (≈ 5–10 s por teste, dentro do ``make test``):

1. ``POST /sessions/{id}/runs`` numa sessão encerrada ⇒ 409 ``SESSION_CLOSED`` (E-09; antes
   404 ``SESSION_NOT_FOUND``, porque o runtime some no fecho);
2. a avaliação só aparece ``completed`` depois do estado da tentativa: quem espera a
   avaliação e volta a submeter, liquida a carreira ou inicia outra tentativa não vê
   ``evaluating`` nem a sessão aberta;
3. motor restaurado e tentativa abandonada sem ``GET`` dela ⇒ a carreira liquida
   ``engine_broken`` (antes ``abandoned``: o restauro só era contado ao ler a tentativa).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa_support import (
    API,
    close_session,
    create_session,
    new_player,
    open_client,
    real_app,
    start_attempt,
    submit,
    wait_attempt_ready,
)


@pytest.fixture
async def real(
    settings_factory: Callable[..., Any],
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = real_app(settings_factory(worker_mode="process"))
    async with open_client(app) as client:
        yield app, client


async def test_run_on_closed_session_is_session_closed(
    real: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    _app, client = real
    session = await create_session(client, vehicle_id="hatch-20t-gdi")
    await close_session(client, session["session_id"])

    resp = await client.post(
        f"{API}/sessions/{session['session_id']}/runs", json={"run_type": "baseline_pull"}
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "SESSION_CLOSED"


async def test_evaluation_is_published_after_the_attempt_state(
    real: tuple[FastAPI, httpx.AsyncClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client = real
    attempts = app.state.scenarios.attempts
    states_when_completed: list[str] = []
    original = attempts.repo.update_evaluation

    async def spy(evaluation_id: str, **changes: Any) -> Any:
        if changes.get("status") == "completed":
            attempt_id = changes["result_json"]["evaluation"]["attempt_id"]
            row = await attempts.repo.get_attempt(attempt_id)
            states_when_completed.append(row.state)
        return await original(evaluation_id, **changes)

    monkeypatch.setattr(attempts.repo, "update_evaluation", spy)
    headers = await new_player(client, "qa_ordem_avaliacao")
    attempt = await start_attempt(client, "stage1-oem", headers)

    evaluation = await submit(client, attempt["attempt_id"], headers, attempt["calibration_id"])

    assert evaluation["status"] == "completed" and evaluation["passed"] is False
    assert states_when_completed == ["in_progress"]
    view = await client.get(f"{API}/attempts/{attempt['attempt_id']}", headers=headers)
    assert view.json()["state"] == "in_progress"
    await client.post(f"{API}/attempts/{attempt['attempt_id']}/abandon", headers=headers)


async def test_restore_then_abandon_settles_engine_broken(
    real: tuple[FastAPI, httpx.AsyncClient],
) -> None:
    _app, client = real
    headers = await new_player(client, "qa_restauro_abandono")
    profile_id = headers["X-Player-Profile-Id"]
    job = (
        await client.post(
            f"{API}/career/profiles/{profile_id}/jobs", json={"order_id": "stage1-diario-seguro"}
        )
    ).json()
    attempt = await wait_attempt_ready(client, job["attempt_id"], headers)
    restored = await client.post(f"{API}/sessions/{attempt['session_id']}/engine/restore")
    assert restored.status_code == 200, restored.text
    abandoned = await client.post(f"{API}/attempts/{job['attempt_id']}/abandon", headers=headers)
    assert abandoned.status_code == 200, abandoned.text

    settled = await client.post(f"{API}/career/jobs/{job['job_id']}/settle")

    assert settled.status_code == 200, settled.text
    assert settled.json()["status"] == "engine_broken"
    assert settled.json()["delta_balance_brl"] == -job["engine_cost_brl"]
