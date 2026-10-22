"""Códigos de erro do ecu-profiles (rest-api 4.7; D-15, D-REST-05, D-REST-06).

Carregado no arranque por ``core.errors.COMPONENT_ERROR_MODULES``. Também se registam,
com o status do dono, os códigos de outros componentes que o ecu-profiles devolve
(``SESSION_NOT_FOUND``, ``SESSION_CLOSED``, ``RUN_IN_PROGRESS``, ``VEHICLE_NOT_FOUND``,
``CALIBRATION_APPLY_TIMEOUT``). O registo repetido com o mesmo status é idempotente.

``NAV_TARGET_NOT_SUPPORTED`` e ``HARDWARE_FILE_MISSING`` são internos (arranque e log):
não têm status HTTP e não entram no catálogo.
"""

from __future__ import annotations

from typing import Any, Final, cast

from simremap.core.errors import SimRemapError, register_error

__all__ = [
    "INTERNAL_CODES",
    "PROFILE_ERROR_CODES",
    "RETRY_AFTER_DB",
    "base_setup_invalid",
    "database_unavailable",
    "profile_error",
]

PROFILE_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("ECU_PROFILE_NOT_FOUND", 404, "Perfil de ECU não encontrado"),
    ("PROFILE_REGISTRY_INVALID", 500, "Registo de perfis de ECU inválido"),
    ("SWAP_TARGET_INVALID", 422, "Perfil alvo da troca inválido"),
    ("SWAP_CONFIRMATION_REQUIRED", 422, "Confirmação do snapshot OEM obrigatória"),
    ("SWAP_NOT_SUPPORTED_FOR_VEHICLE", 422, "Veículo sem suporte à troca de ECU"),
    ("BASE_SETUP_NOT_EDITABLE_OEM", 409, "Configuração base fixa no perfil OEM"),
    ("BASE_SETUP_VERSION_CONFLICT", 409, "Conflito de versão da configuração base"),
    ("BASE_SETUP_INVALID", 422, "Configuração base inválida"),
    ("WIZARD_INPUT_INVALID", 422, "Entrada do assistente inválida"),
    ("ECU_SETUP_INCOMPLETE", 409, "Configuração mínima da ECU incompleta"),
    ("OEM_CHECKSUM_INVALID", 422, "Checksum OEM inválido"),
    ("OEM_TORQUE_MODEL_NOT_MONOTONIC", 422, "Modelo de torque OEM não invertível"),
    ("TABLE_NOT_SUPPORTED_BY_PROFILE", 422, "Tabela não suportada pelo perfil"),
    ("STRATEGY_REQUIRES_PACKAGE", 422, "Estratégia exige o pacote race"),
    ("STRATEGY_OPTION_NOT_SUPPORTED", 422, "Opção de estratégia não suportada pelo perfil"),
    # Códigos de outros donos devolvidos pelo ecu-profiles (mesmo status do dono).
    ("SESSION_NOT_FOUND", 404, "Sessão não encontrada"),
    ("SESSION_CLOSED", 409, "Sessão encerrada"),
    ("RUN_IN_PROGRESS", 409, "Puxada em andamento"),
    ("VEHICLE_NOT_FOUND", 404, "Veículo não encontrado"),
    ("CALIBRATION_APPLY_TIMEOUT", 504, "O worker não confirmou a aplicação da calibração"),
)

INTERNAL_CODES: Final = frozenset({"NAV_TARGET_NOT_SUPPORTED", "HARDWARE_FILE_MISSING"})

for _code, _status, _title in PROFILE_ERROR_CODES:
    register_error(_code, _status, _title)

RETRY_AFTER_DB: Final = {"Retry-After": "2"}


def profile_error(
    code: str, detail: str, *, headers: dict[str, str] | None = None, **extra: object
) -> SimRemapError:
    """``SimRemapError`` de um código registado com campos extra no ``ProblemDetail``."""
    return SimRemapError(detail, code=code, headers=headers, **cast(dict[str, Any], extra))


def base_setup_invalid(field: str, reason: str) -> SimRemapError:
    """422 ``BASE_SETUP_INVALID`` com ``field`` (caminho com pontos) e ``reason``."""
    return profile_error(
        "BASE_SETUP_INVALID",
        f"Campo inválido na configuração base: {field} ({reason}).",
        field=field,
        reason=reason,
    )


def database_unavailable() -> SimRemapError:
    return SimRemapError(
        "Banco de dados indisponível; tente de novo em instantes.",
        code="DATABASE_UNAVAILABLE",
        headers=RETRY_AFTER_DB,
    )
