"""Códigos de erro do catálogo (rest-api 4.2; vehicle-catalog seção 8).

Os códigos HTTP são registados no catálogo único da fundação por subclasse de
``SimRemapError``. ``CATALOG_INVALID`` só existe no arranque (saída 4); os subcódigos
internos de validação (``FILE_HASH_MISMATCH``, ``GRID_AXIS_NOT_MONOTONIC``...) vão
apenas para o log ``startup.failed`` (``contracts/file-formats.md`` seção 2.7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from simremap.core.errors import SimRemapError

__all__ = [
    "CATALOG_EXIT_CODE",
    "INTERNAL_CODES",
    "CatalogInvalid",
    "CatalogIssue",
    "FuelNotAllowed",
    "FuelNotFound",
    "ReferenceCurveNotFound",
    "UpgradeNotCompatible",
    "VehicleIdInvalid",
    "VehicleNotFound",
    "VehicleNotValidated",
]

CATALOG_EXIT_CODE: Final = 4
"""Código de saída do processo quando o catálogo é inválido (RF-01)."""

INTERNAL_CODES: Final[frozenset[str]] = frozenset(
    {
        # contracts/file-formats.md seção 2.7
        "FILE_HASH_MISMATCH",
        "FILE_NOT_IN_MANIFEST",
        "FILE_TOO_LARGE",
        "PATH_OUTSIDE_CATALOG",
        "GRID_AXIS_NOT_MONOTONIC",
        "GRID_SHAPE_MISMATCH",
        "GRID_VALUE_OUT_OF_RANGE",
        "TRADEMARK_IN_DISPLAY_TEXT",
        "REFERENCE_CURVE_INCONSISTENT",
        "REFERENCE_POINT_MISSING_VALUE",
        "CALIBRATION_VALIDATOR_ERROR",
        # complementares (só log de arranque; mesma regra de saída 4)
        "CATALOG_DIR_UNAVAILABLE",
        "MANIFEST_INVALID",
        "FILE_MISSING",
        "FILE_ENCODING_INVALID",
        "JSON_INVALID",
        "SCHEMA_INVALID",
        "CATALOG_LAYOUT_INVALID",
        "VEHICLE_ID_MISMATCH",
        "CATALOG_VEHICLES_MISMATCH",
        "REFERENCE_CURVE_INVALID",
        "PROVENANCE_POINTER_INVALID",
        "CALIBRATION_INVALID",
    }
)


@dataclass(frozen=True, slots=True)
class CatalogIssue:
    """Um erro de validação do catálogo: arquivo, ponteiro JSON e subcódigo interno."""

    code: str
    file: str  # caminho relativo à raiz do catálogo, com "/"
    pointer: str  # ponteiro JSON (RFC 6901); "" = arquivo inteiro
    message: str

    def as_log(self) -> dict[str, str]:
        return {
            "code": self.code,
            "file": self.file,
            "pointer": self.pointer,
            "message": self.message,
        }


class VehicleNotFound(SimRemapError):
    code = "VEHICLE_NOT_FOUND"
    status = 404
    title = "Veículo não encontrado"


class VehicleIdInvalid(SimRemapError):
    code = "VEHICLE_ID_INVALID"
    status = 422
    title = "Identificador de veículo inválido"


class VehicleNotValidated(SimRemapError):
    code = "VEHICLE_NOT_VALIDATED"
    status = 409
    title = "Veículo ainda não validado"


class ReferenceCurveNotFound(SimRemapError):
    code = "REFERENCE_CURVE_NOT_FOUND"
    status = 404
    title = "Curva de referência não encontrada"


class FuelNotFound(SimRemapError):
    code = "FUEL_NOT_FOUND"
    status = 404
    title = "Combustível não encontrado"


class FuelNotAllowed(SimRemapError):
    code = "FUEL_NOT_ALLOWED"
    status = 409
    title = "Combustível não permitido para o veículo"


class UpgradeNotCompatible(SimRemapError):
    code = "UPGRADE_NOT_COMPATIBLE"
    status = 422
    title = "Peça incompatível com o veículo"


class CatalogInvalid(SimRemapError):
    """Catálogo inválido no arranque; nunca chega a uma resposta HTTP (saída 4)."""

    code = "CATALOG_INVALID"
    status = 500
    title = "Catálogo de veículos inválido"

    exit_code: int = CATALOG_EXIT_CODE

    def __init__(self, issues: list[CatalogIssue]) -> None:
        first = issues[0] if issues else CatalogIssue("SCHEMA_INVALID", "", "", "sem detalhe")
        detail = f"{len(issues)} erro(s) no catálogo; primeiro: {first.code} em {first.file}"
        super().__init__(detail, issues=[issue.as_log() for issue in issues])
        self.issues: list[CatalogIssue] = list(issues)
