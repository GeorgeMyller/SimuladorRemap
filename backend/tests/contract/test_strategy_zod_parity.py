"""Paridade zod × Pydantic de ``StrategyConfig`` (ecu-tuning-ui RF-14, EC-13).

O mesmo conjunto de 40 payloads (20 válidos, 20 inválidos) de
``frontend/src/features/ecu-tuning/fixtures/strategy-parity.json`` corre no vitest
(``StrategyForms.test.tsx``) e aqui; os dois lados devem dar o veredito esperado.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from simremap.ecu.contracts import StrategyConfig

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/features/ecu-tuning/fixtures/strategy-parity.json"
)

pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="fixture do frontend ausente")


def _cases() -> list[dict[str, Any]]:
    if not FIXTURE.exists():
        return []
    data: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    return cases


def test_fixture_tem_20_validos_e_20_invalidos() -> None:
    cases = _cases()
    assert sum(1 for c in cases if c["valid"]) == 20
    assert sum(1 for c in cases if not c["valid"]) == 20


@pytest.mark.parametrize("case", _cases(), ids=lambda c: str(c["name"]))
def test_veredito_pydantic(case: dict[str, Any]) -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(StrategyConfig)
    try:
        adapter.validate_python(case["payload"])
        valid = True
    except ValidationError:
        valid = False
    assert valid is case["valid"]
