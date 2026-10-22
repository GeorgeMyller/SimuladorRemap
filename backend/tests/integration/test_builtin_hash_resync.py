"""Autocura do hash do ``stage1-oem`` com a porta real do ecu-core (002 T006; D-01, D-02).

App completa (catálogo real, série semeada, ``EcuCalibrationPort``). Causa raiz do 422
``SCENARIO_CALIBRATION_HASH_MISMATCH``: o clone recalcula o ``content_hash`` no servidor a
partir do conteúdo, enquanto o cenário guardava o ``content_hash`` gravado na v1 da série.

1. arranque: o hash do cenário é o da rota do clone (``parse_content`` + recálculo);
2. v1 da série alterada no banco ⇒ a tentativa usa a cópia de fábrica do catálogo (201);
3. hash do cenário velho e fábrica divergente ⇒ o cenário é ressincronizado com o clone (201).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from sqlalchemy import select
from sqlmodel import col

from simremap.api.main import create_app
from simremap.db.models.calibration import CalibrationVersionRow
from simremap.ecu.calibration import compute_content_hash, parse_content
from simremap.scenarios.ports import CalibrationRecord

STOCK_ID = "stock-hatch-20t-gdi-oem-stage"
SCENARIO_ID = "stage1-oem"


@pytest.fixture
async def real(settings_factory: Callable[..., Any]) -> AsyncIterator[tuple[FastAPI, Any]]:
    app = create_app(settings_factory())
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=60) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield app, client


async def _stock(app: FastAPI) -> CalibrationRecord:
    record: CalibrationRecord | None = await app.state.scenarios.catalog.calibrations.stock(
        "hatch-20t-gdi", "oem-stage"
    )
    assert record is not None
    return record


def _nudge_first_cell(payload: dict[str, Any]) -> None:
    """Muda uma célula de uma tabela 3D (sem mexer no ``content_hash`` guardado)."""
    for table in payload["tables"].values():
        values = table["values"]
        if values and isinstance(values[0], list):
            values[0][0] = values[0][0] + 0.5
            return
    raise AssertionError("série sem tabela 3D")


async def _tamper_v1(app: FastAPI) -> None:
    async with app.state.sessionmaker() as db:
        row = (
            await db.scalars(
                select(CalibrationVersionRow).where(
                    col(CalibrationVersionRow.calibration_id) == STOCK_ID,
                    col(CalibrationVersionRow.version) == 1,
                )
            )
        ).one()
        payload = json.loads(row.payload_json)
        _nudge_first_cell(payload)
        row.payload_json = json.dumps(payload)
        await db.commit()


async def _start(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, str]]:
    created = await client.post("/api/v1/profiles", json={"nickname": "lucas_turbo"})
    assert created.status_code == 201, created.text
    headers = {"X-Player-Profile-Id": created.json()["profile_id"]}
    started = await client.post(f"/api/v1/scenarios/{SCENARIO_ID}/attempts", headers=headers)
    assert started.status_code == 201, started.text
    body: dict[str, Any] = started.json()
    return body, headers


async def _clone_hash(client: httpx.AsyncClient, attempt: dict[str, Any]) -> str:
    resp = await client.get(f"/api/v1/calibrations/{attempt['calibration_id']}")
    assert resp.status_code == 200, resp.text
    return str(resp.json()["content_hash"])


async def test_builtin_hash_comes_from_clone_route(real: tuple[FastAPI, Any]) -> None:
    app, _client = real
    stock = await _stock(app)
    scenario = await app.state.scenarios.catalog.get(SCENARIO_ID)
    expected = compute_content_hash(parse_content(stock.content))
    assert scenario.initial_calibration.content_hash == expected


async def test_tampered_stock_v1_uses_factory_clone(real: tuple[FastAPI, Any]) -> None:
    app, client = real
    before = await app.state.scenarios.catalog.get(SCENARIO_ID)
    await _tamper_v1(app)
    stock = await _stock(app)
    assert app.state.scenarios.catalog.calibrations.clone_hash(stock) != (
        before.initial_calibration.content_hash
    )

    attempt, _headers = await _start(client)

    after = await app.state.scenarios.catalog.get(SCENARIO_ID)
    assert await _clone_hash(client, attempt) == after.initial_calibration.content_hash
    assert after.scenario_sha256 == before.scenario_sha256
    assert attempt["scenario_sha256"] == after.scenario_sha256


async def test_stale_scenario_hash_is_resynced(real: tuple[FastAPI, Any]) -> None:
    app, client = real
    catalog = app.state.scenarios.catalog
    stale = await catalog.resync_builtin_hash(SCENARIO_ID, "0" * 64)

    attempt, _headers = await _start(client)

    after = await catalog.get(SCENARIO_ID)
    clone_hash = await _clone_hash(client, attempt)
    assert clone_hash == after.initial_calibration.content_hash
    assert after.initial_calibration.content_hash != "0" * 64
    assert after.scenario_sha256 != stale.scenario_sha256
    assert attempt["scenario_sha256"] == after.scenario_sha256
