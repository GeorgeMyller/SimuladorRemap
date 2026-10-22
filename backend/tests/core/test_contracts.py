"""Contratos comuns (T016, data-model D-04)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from simremap.core.contracts import (
    ContractModel,
    EntityId,
    Sha256Hex,
    SimStrEnum,
    is_entity_id,
)

_entity = TypeAdapter(EntityId)


@pytest.mark.parametrize(
    "value",
    [
        "hatch-20t-gdi",
        "stock-hatch-20t-gdi-oem-stage",
        "0f5e9c2a",
        "a",
        "a_b-c",
        "a" * 64,
        "6c1f0a7e-1d2b-4c3a-9f10-2b3c4d5e6f70",
    ],
)
def test_entity_id_accepts(value: str) -> None:
    assert _entity.validate_python(value) == value
    assert is_entity_id(value)


@pytest.mark.parametrize("value", ["", "-abc", "_abc", "ABC", "a b", "a" * 65, "ação", "a/b"])
def test_entity_id_rejects(value: str) -> None:
    with pytest.raises(ValidationError):
        _entity.validate_python(value)
    assert not is_entity_id(value)


def test_sha256_hex() -> None:
    adapter = TypeAdapter(Sha256Hex)
    assert adapter.validate_python("a" * 64)
    with pytest.raises(ValidationError):
        adapter.validate_python("A" * 64)


class _Sample(ContractModel):
    vehicle_id: EntityId
    rpm: float


def test_contract_model_frozen_and_forbid_extra() -> None:
    sample = _Sample(vehicle_id="hatch-20t-gdi", rpm=3000.0)
    with pytest.raises(ValidationError):
        sample.rpm = 1.0
    with pytest.raises(ValidationError):
        _Sample.model_validate({"vehicle_id": "x", "rpm": 1.0, "extra": 1})


class _Mode(SimStrEnum):
    STEADY = "steady_state"
    SWEEP = "sweep"


def test_sim_str_enum_helpers() -> None:
    assert _Mode.values() == ("steady_state", "sweep")
    assert _Mode.check_sql("run_type") == "run_type IN ('steady_state', 'sweep')"
    assert _Mode("sweep") is _Mode.SWEEP
    assert f"{_Mode.SWEEP}" == "sweep"
