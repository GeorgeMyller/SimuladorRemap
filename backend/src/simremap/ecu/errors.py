"""Códigos de erro do ecu-core (rest-api 4.6; D-15, D-REST-05).

``DATABASE_UNAVAILABLE`` (503, ``Retry-After: 2``) é o código transversal da fundação
(``STORAGE_UNAVAILABLE`` está aposentado). Também se registam, com o mesmo status do
dono, os códigos de outros componentes que o ecu-core devolve: ``SESSION_NOT_FOUND``
(dyno-bench), ``VEHICLE_NOT_FOUND`` (vehicle-catalog) e ``ECU_PROFILE_NOT_FOUND``
(ecu-profiles). O registo repetido com o mesmo status é idempotente.
"""

from __future__ import annotations

from typing import Any, Final, cast

from simremap.core.errors import SimRemapError, is_registered, register_error
from simremap.ecu.contracts import EcuValidationError

__all__ = [
    "ECU_ERROR_CODES",
    "RETRY_AFTER_DB",
    "database_unavailable",
    "ecu_error",
    "from_validation",
]

ECU_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("CALIBRATION_NOT_FOUND", 404, "Calibração não encontrada"),
    ("CALIBRATION_VERSION_NOT_FOUND", 404, "Versão de calibração não encontrada"),
    ("CALIBRATION_VERSION_CONFLICT", 409, "Conflito de versão da calibração"),
    ("CALIBRATION_VERSION_LIMIT", 409, "Limite de versões da calibração atingido"),
    ("CALIBRATION_PROFILE_IMMUTABLE", 422, "O perfil da calibração não pode mudar"),
    ("CALIBRATION_STOCK_IMMUTABLE", 409, "Calibração de fábrica somente leitura"),
    ("CALIBRATION_PROFILE_MISMATCH", 422, "Perfil da calibração diferente do da sessão"),
    ("CALIBRATION_VEHICLE_MISMATCH", 422, "Veículo da calibração diferente do da sessão"),
    ("CALIBRATION_APPLY_TIMEOUT", 504, "O worker não confirmou a aplicação da calibração"),
    ("TABLE_NOT_FOUND", 404, "Tabela não encontrada"),
    ("TABLE_NOT_LIVE_TUNABLE", 409, "Alteração não permitida durante a puxada"),
    ("TABLE_AXIS_NOT_MONOTONIC", 422, "Eixo de tabela não estritamente crescente"),
    ("TABLE_SIZE_EXCEEDED", 422, "Tabela acima do tamanho máximo"),
    ("TABLE_VALUE_NOT_FINITE", 422, "Valor de tabela não finito"),
    ("TABLE_VALUE_OUT_OF_RANGE", 422, "Valor fora do limite da tabela"),
    ("TABLE_SHAPE_MISMATCH", 422, "Formato da tabela diferente dos eixos"),
    ("TABLE_UNIT_MISMATCH", 422, "Unidade da tabela diferente da prevista"),
    ("TABLE_ID_MISMATCH", 422, "Identificador de tabela inconsistente"),
    ("STRATEGY_KIND_MISMATCH", 422, "Chave de estratégia diferente do kind"),
    ("STRATEGY_CONFIG_INVALID", 422, "Configuração de estratégia incoerente"),
    ("STRATEGY_NOT_SUPPORTED_BY_PROFILE", 422, "Estratégia não suportada pelo perfil"),
    ("PATCH_TOO_LARGE", 422, "PATCH com células demais"),
    ("PATCH_CELL_OUT_OF_BOUNDS", 422, "Célula fora da tabela"),
    # Códigos de outros donos devolvidos pelo ecu-core (mesmo status do dono).
    ("SESSION_NOT_FOUND", 404, "Sessão não encontrada"),
    ("VEHICLE_NOT_FOUND", 404, "Veículo não encontrado"),
    ("ECU_PROFILE_NOT_FOUND", 404, "Perfil de ECU não encontrado"),
)

for _code, _status, _title in ECU_ERROR_CODES:
    register_error(_code, _status, _title)

RETRY_AFTER_DB: Final = {"Retry-After": "2"}

_DETAILS: Final[dict[str, str]] = {
    "TABLE_AXIS_NOT_MONOTONIC": "O eixo {quantity} deve ser estritamente crescente.",
    "TABLE_SIZE_EXCEEDED": "A tabela excede o tamanho máximo (32 pontos por eixo, 128 tabelas).",
    "TABLE_VALUE_NOT_FINITE": "A tabela {table_id} tem um valor não finito.",
    "TABLE_VALUE_OUT_OF_RANGE": (
        "A célula ({row}, {col}) da tabela {table_id} vale {value} e o limite é {min} a {max}."
    ),
    "TABLE_SHAPE_MISMATCH": "As dimensões da tabela {table_id} não batem com os eixos.",
    "TABLE_UNIT_MISMATCH": "A tabela {table_id} usa {got}; a unidade prevista é {expected}.",
    "TABLE_ID_MISMATCH": "A chave {key} não corresponde a uma tabela válida.",
    "STRATEGY_KIND_MISMATCH": "A chave {key} não corresponde ao kind {kind}.",
    "STRATEGY_CONFIG_INVALID": "Configuração de estratégia incoerente: {reason}.",
    "STRATEGY_NOT_SUPPORTED_BY_PROFILE": "O perfil {profile_id} não suporta {strategy}.",
    "PATCH_TOO_LARGE": "O PATCH tem {cells} células; o máximo é {max}.",
    "PATCH_CELL_OUT_OF_BOUNDS": "A célula ({row}, {col}) está fora da tabela {table_id}.",
    "CALIBRATION_STOCK_IMMUTABLE": (
        "Calibrações de fábrica são somente leitura; clone antes de editar."
    ),
}


def ecu_error(code: str, detail: str | None = None, **extra: object) -> SimRemapError:
    """``SimRemapError`` de um código registado; código desconhecido vira ``VALIDATION_FAILED``."""
    text = detail
    if text is None:
        template = _DETAILS.get(code)
        try:
            text = template.format(**extra) if template else None
        except (KeyError, IndexError):
            text = None
    fields = cast(dict[str, Any], extra)
    if not is_registered(code):
        return SimRemapError(text or code, code="VALIDATION_FAILED", reason=code, **fields)
    return SimRemapError(text or code.replace("_", " ").capitalize() + ".", code=code, **fields)


def from_validation(exc: EcuValidationError) -> SimRemapError:
    """Converte o erro de domínio (``code`` + ``detail``) no ``ProblemDetail`` do router."""
    extra = {k: (v.value if hasattr(v, "value") else v) for k, v in exc.detail.items()}
    extra.pop("detail", None)
    message = exc.detail.get("detail")
    return ecu_error(exc.code, str(message) if message is not None else None, **extra)


def database_unavailable() -> SimRemapError:
    return SimRemapError(
        "Banco de dados indisponível; tente de novo em instantes.",
        code="DATABASE_UNAVAILABLE",
        headers=RETRY_AFTER_DB,
    )
