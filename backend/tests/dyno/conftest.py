"""Fixtures do dyno-bench: laço sem worker e app REST com o hatch calibrado da física.

- ``dyno_task_factory``: ``make_task(**over)`` (``DynoSimTask`` com ``setup`` feito).
- ``calibration_source``: ``FixtureCalibrationSource`` (calibração de série afinada).
- ``dyno_app``/``dyno_client``: ``make_dyno_app`` (``dyno_helpers``) com worker ``process``
  (o modo ``thread`` com vários passos por tick disputa o GIL com o event loop e torna os
  testes REST muito lentos), ``hatch-20t-gdi`` da fixture da física, ``profile_hooks =
  "null"``, dano ``MECHANICAL_DAMAGE`` e ``steps_per_tick = 10`` (o determinismo não muda).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dyno_helpers import FixtureCalibrationSource, make_dyno_app, make_task

from simremap.dyno.runner import DynoSimTask

TaskFactory = Callable[..., DynoSimTask]


@pytest.fixture
def dyno_task_factory() -> TaskFactory:
    return make_task


@pytest.fixture
def calibration_source() -> FixtureCalibrationSource:
    return FixtureCalibrationSource()


@pytest.fixture
def dyno_app(
    settings_factory: Callable[..., Any], calibration_source: FixtureCalibrationSource
) -> FastAPI:
    app: FastAPI = make_dyno_app(settings_factory(worker_mode="process"), calibration_source)
    return app


@pytest.fixture
async def dyno_client(dyno_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with LifespanManager(dyno_app, startup_timeout=30, shutdown_timeout=30) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", timeout=60.0
        ) as client:
            yield client
