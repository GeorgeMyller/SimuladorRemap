"""Tipos e bases comuns dos contratos Pydantic de todos os componentes.

Regras (data-model D-04, platform-foundation seção 8):
- ``EntityId``: identificador canônico em minúsculas, 1 a 64 caracteres
  (``^[0-9a-z][-_0-9a-z]{0,63}$``). Aceita slugs (``hatch-20t-gdi``), UUID4 em
  texto ou hex e ``stock-<vehicle_id>-<profile_id>``.
- ``ContractModel``: base imutável (``frozen=True``) que recusa campos extra.
- ``SimStrEnum``: base das enumerações persistidas como ``String(n)``.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, StringConstraints

__all__ = [
    "CONTRACT_CONFIG",
    "ENTITY_ID_PATTERN",
    "ENTITY_ID_REGEX",
    "SHA256_HEX_PATTERN",
    "ContractModel",
    "EntityId",
    "Sha256Hex",
    "SimStrEnum",
    "is_entity_id",
]

ENTITY_ID_PATTERN: Final = r"^[0-9a-z][-_0-9a-z]{0,63}$"
ENTITY_ID_REGEX: Final = re.compile(ENTITY_ID_PATTERN)
SHA256_HEX_PATTERN: Final = r"^[0-9a-f]{64}$"

EntityId = Annotated[str, StringConstraints(pattern=ENTITY_ID_PATTERN)]
"""Identificador canônico (slug, UUID em texto ou hex) com no máximo 64 caracteres."""

Sha256Hex = Annotated[str, StringConstraints(pattern=SHA256_HEX_PATTERN)]
"""SHA-256 em hexadecimal minúsculo (64 caracteres)."""

CONTRACT_CONFIG: Final = ConfigDict(frozen=True, extra="forbid")
"""Configuração comum dos contratos: imutável e sem campos desconhecidos."""


class ContractModel(BaseModel):
    """Base dos contratos de fronteira (REST, WS, barramento, arquivos)."""

    model_config = CONTRACT_CONFIG


class SimStrEnum(StrEnum):
    """Base das enumerações do domínio (valores em ``snake_case``)."""

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Devolve os valores na ordem de declaração (útil para ``CheckConstraint``)."""
        return tuple(member.value for member in cls)

    @classmethod
    def check_sql(cls, column: str) -> str:
        """Expressão SQL ``column IN (...)`` para ``CheckConstraint`` em SQLite e PostgreSQL."""
        quoted = ", ".join(f"'{value}'" for value in cls.values())
        return f"{column} IN ({quoted})"


def is_entity_id(value: str) -> bool:
    """Indica se ``value`` casa com ``ENTITY_ID_PATTERN``."""
    return ENTITY_ID_REGEX.fullmatch(value) is not None
