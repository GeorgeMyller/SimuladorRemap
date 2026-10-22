"""Fixtures do telemetry-datalogger.

- ``hatch_record``: ``TickRecord`` real do laço do hatch (fixture da física, 4 cilindros).
- ``e2e_app``/``e2e_client``: app completa (dyno + telemetria) com worker ``process`` e
  ``TestClient`` síncrono (WebSocket real); ``steps_per_tick = 10``.
- ``tel_client``: ``httpx.AsyncClient`` sobre a app padrão (REST da telemetria, banco
  migrado) e ``tel_service``: o ``TelemetryService`` dessa app.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tel_helpers import capture_record, make_e2e_app

from simremap.api.main import create_app
from simremap.dyno.sampler import TickRecord
from simremap.telemetry.service import TelemetryService


@pytest.fixture(scope="session")
def hatch_record() -> TickRecord:
    return capture_record()


@pytest.fixture
def e2e_app(settings_factory: Callable[..., Any]) -> FastAPI:
    app: FastAPI = make_e2e_app(settings_factory(worker_mode="process"))
    return app


@pytest.fixture
def e2e_client(e2e_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(e2e_app) as client:
        yield client


@pytest.fixture
def tel_app(settings_factory: Callable[..., Any]) -> FastAPI:
    return create_app(settings_factory())


@pytest.fixture
async def tel_client(tel_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(tel_app, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield client


@pytest.fixture
def tel_service(tel_app: FastAPI, tel_client: httpx.AsyncClient) -> TelemetryService:
    service: TelemetryService = tel_app.state.telemetry_service
    return service
