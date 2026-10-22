"""Tipos e auxiliares de coluna partilhados pelos modelos de domínio (data-model 1.2).

- ``JSONType``: ``JSON`` com variante ``JSONB`` em PostgreSQL (texto em SQLite).
- ``check_in``: ``CheckConstraint`` ``coluna IN (...)`` com nome curto (a convenção
  ``ck_<tabela>_<nome>`` completa o nome final).
- ``check_expr``: ``CheckConstraint`` com expressão livre.
- Conjuntos de valores comuns: perfis de ECU e combustíveis.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

from sqlalchemy import JSON, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine

from simremap.catalog.contracts import FUEL_IDS, PROFILE_IDS

__all__ = [
    "ECU_PROFILE_IDS",
    "FUEL_ID_VALUES",
    "SEED_MAX",
    "JSONType",
    "check_expr",
    "check_in",
]

SEED_MAX: Final = 2**63 - 1
ECU_PROFILE_IDS: Final[tuple[str, ...]] = PROFILE_IDS
FUEL_ID_VALUES: Final[tuple[str, ...]] = FUEL_IDS

JSONType: Final[TypeEngine[Any]] = JSON().with_variant(JSONB(), "postgresql")


def check_in(column: str, values: Iterable[str], name: str | None = None) -> CheckConstraint:
    """``CHECK (column IN (...))`` com nome ``name`` (padrão: nome da coluna)."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=name or column)


def check_expr(expression: str, name: str) -> CheckConstraint:
    """``CHECK (expression)`` com nome curto."""
    return CheckConstraint(expression, name=name)
