"""Códigos de erro do Modo Carreira (002 interfaces/career.md; ``application/problem+json``).

Registados no catálogo único ao importar o módulo (o router importa-o no arranque).
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = ["CAREER_ERROR_CODES", "career_error"]

CAREER_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("CAREER_ORDER_NOT_FOUND", 404, "Ordem de serviço não encontrada"),
    ("CAREER_JOB_NOT_FOUND", 404, "Serviço da carreira não encontrado"),
    ("CAREER_REPUTATION_TOO_LOW", 409, "Reputação insuficiente para a ordem"),
    ("CAREER_JOB_ALREADY_OPEN", 409, "Já existe um serviço em aberto"),
    ("CAREER_ATTEMPT_NOT_FINISHED", 409, "Tentativa do serviço ainda em andamento"),
)

for _code, _status, _title in CAREER_ERROR_CODES:
    register_error(_code, _status, _title)


def career_error(code: str, detail: str, **extra: object) -> SimRemapError:
    """``SimRemapError`` com um código da carreira e campos extra no ``ProblemDetail``."""
    error = SimRemapError(detail, code=code)
    error.extra.update(extra)
    return error
