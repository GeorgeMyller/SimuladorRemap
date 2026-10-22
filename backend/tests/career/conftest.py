"""Fixtures do Modo Carreira: a estação dos testes dos cenários (``tests/scenarios/scn_env``)
com as portas falsas de simulação, calibração e catálogo.

- ``car``: ``ScnEnv`` com ``client`` (httpx), ``sim`` (``FakeSimulation``) e ``services``.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scenarios"))

from scn_env import ScnEnv, make_station, open_station


@pytest.fixture
async def car(settings_factory: Callable[..., Any], tmp_path: Path) -> AsyncIterator[ScnEnv]:
    async with open_station(make_station(settings_factory, tmp_path, "oficina")) as env:
        yield env
