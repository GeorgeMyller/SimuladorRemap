"""Fixtures do knock-and-failure-model com ``CombustionEvent``/``EngineState`` sintéticos.

A física ainda não está integrada: os testes alimentam o ``DamageModel`` com estados
construídos em ``kfm_helpers.py`` com os números das RFs da spec.

- ``hatch_vehicle`` / ``v8_vehicle``: ``VehicleSpec`` do ``hatch-20t-gdi`` (Apêndice E) e
  de um V8 com compressor (sem turbina).
- ``e27``: ``FuelSpec`` E27 (RON 95, MON 81 ⇒ ON 88).
- ``make_model``: fábrica de ``DamageModel`` (padrão: ``SPEC_CONFIG``, coeficientes literais
  das RFs; o ``DamageConfig`` padrão calibrado é testado em ``test_contracts.py``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kfm_helpers import SESSION, SPEC_CONFIG, ModelFactory, build_e27, build_hatch, build_v8

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.damage.model import DamageModel


@pytest.fixture(scope="session")
def hatch_vehicle() -> VehicleSpec:
    return build_hatch()


@pytest.fixture(scope="session")
def v8_vehicle() -> VehicleSpec:
    return build_v8()


@pytest.fixture(scope="session")
def e27() -> FuelSpec:
    return build_e27()


@pytest.fixture
def make_model(hatch_vehicle: VehicleSpec, e27: FuelSpec) -> ModelFactory:
    def factory(
        config: DamageConfig | None = None,
        *,
        vehicle: VehicleSpec | None = None,
        seed: int = 42,
        damage_enabled: bool = True,
        **kwargs: Any,
    ) -> DamageModel:
        return DamageModel(
            config or SPEC_CONFIG,
            vehicle or hatch_vehicle,
            e27,
            seed,
            damage_enabled,
            session_id=kwargs.pop("session_id", SESSION),
            **kwargs,
        )

    return factory
