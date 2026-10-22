"""Fixtures de integração do dyno-bench (reutiliza ``tests/dyno/dyno_helpers.py``)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dyno"))

from dyno_helpers import FixtureCalibrationSource, make_dyno_app


@pytest.fixture
def integration_app(settings_factory: Callable[..., Any]) -> FastAPI:
    app: FastAPI = make_dyno_app(
        settings_factory(worker_mode="process"), FixtureCalibrationSource()
    )
    return app


@pytest.fixture
async def integration_client(integration_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(integration_app, startup_timeout=30, shutdown_timeout=30) as m:
        transport = httpx.ASGITransport(app=m.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield client
