"""T413: validador de ``Calibration`` do ecu-core no loader do catálogo (catalog RF-20)."""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

from simremap.catalog.errors import CatalogInvalid
from simremap.catalog.loader import (
    CALIBRATION_VALIDATOR_MODULES,
    register_calibration_validator,
    registered_calibration_validators,
)
from simremap.ecu.calibration import validate_catalog_calibration

HATCH_CAL = "vehicles/hatch-20t-gdi/calibrations/oem-stage.json"


def _codes(exc: pytest.ExceptionInfo[CatalogInvalid]) -> list[str]:
    return [issue.code for issue in exc.value.issues]


def test_ecu_module_registers_validator_on_import() -> None:
    """Num processo limpo, a carga do catálogo importa o ecu-core e usa o validador dele."""
    assert CALIBRATION_VALIDATOR_MODULES == ("simremap.ecu.calibration",)
    code = (
        "from simremap.catalog.loader import load_catalog_data, "
        "registered_calibration_validators as r\n"
        "load_catalog_data()\n"
        "print([f.__module__ + ':' + f.__name__ for f in r()])\n"
    )
    out = subprocess.run(  # noqa: S603 - interpretador atual com código fixo
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert "simremap.ecu.calibration:validate_catalog_calibration" in out.stdout


def test_real_catalog_passes_the_ecu_validator(catalog_copy: Any) -> None:
    register_calibration_validator(validate_catalog_calibration)
    assert registered_calibration_validators() == (validate_catalog_calibration,)
    catalog = catalog_copy.load()
    assert len(catalog.vehicles) == 4


def test_non_monotonic_axis_becomes_catalog_invalid(catalog_copy: Any) -> None:
    register_calibration_validator(validate_catalog_calibration)

    def break_axis(data: dict[str, Any]) -> None:
        axis = data["tables"]["ve"]["x"]["values"]
        axis[1], axis[2] = axis[2], axis[1]

    catalog_copy.edit(HATCH_CAL, break_axis)
    with pytest.raises(CatalogInvalid) as exc:
        catalog_copy.load()
    assert _codes(exc) == ["TABLE_AXIS_NOT_MONOTONIC"]
    assert exc.value.issues[0].file == HATCH_CAL
    assert exc.value.exit_code == 4


def test_content_hash_mismatch_is_rejected(catalog_copy: Any) -> None:
    register_calibration_validator(validate_catalog_calibration)
    catalog_copy.edit(HATCH_CAL, lambda d: d.update(content_hash="0" * 64))
    with pytest.raises(CatalogInvalid) as exc:
        catalog_copy.load()
    assert _codes(exc) == ["CALIBRATION_INVALID"]


def test_validator_requires_ids() -> None:
    with pytest.raises(ValueError, match="CALIBRATION_INVALID"):
        validate_catalog_calibration({"tables": {}})
