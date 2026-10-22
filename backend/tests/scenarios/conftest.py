"""Fixtures dos testes do training-scenarios.

- ``scn_app``: app real (``create_app``) com as portas falsas de simulação, calibração e
  catálogo (``scn_helpers``); o banco SQLite é migrado pelo lifespan (``0007``).
- ``scn``: ``ScnEnv`` (``scn_env``) com ``client`` (httpx), ``sim`` (``FakeSimulation``),
  ``cals`` (``FakeCalibrations``), ``services`` (``app.state.scenarios``) e atalhos.
- ``instructor_station``: segunda estação com banco próprio (importa os pacotes).
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scn_env import ScnEnv, make_station, open_station
from scn_helpers import FakeCalibrations, FakeSimulation, fake_vehicles

from simremap.api.main import create_app


@pytest.fixture
def scn_app(settings_factory: Callable[..., Any]) -> FastAPI:
    app = create_app(settings_factory())
    cals = FakeCalibrations()
    app.state.scenarios_calibration_port = cals
    app.state.scenarios_sim_port = FakeSimulation(cals)
    app.state.scenarios_vehicle_lookup = fake_vehicles
    return app


@pytest.fixture
async def scn(scn_app: FastAPI) -> AsyncIterator[ScnEnv]:
    async with open_station(scn_app) as env:
        yield env


@pytest.fixture
async def instructor_station(
    settings_factory: Callable[..., Any], tmp_path: Path
) -> AsyncIterator[ScnEnv]:
    """Segunda estação (banco próprio): a do instrutor que importa os pacotes."""
    async with open_station(make_station(settings_factory, tmp_path, "instrutor")) as env:
        yield env
