"""Códigos de erro do knock-and-failure-model (rest-api 4.5; D-REST-11; spec seção 8).

Os códigos ``SESSION_NOT_FOUND``, ``RUN_NOT_FOUND``, ``RUN_IN_PROGRESS``,
``SESSION_CLOSED`` e ``ENGINE_DESTROYED`` pertencem ao ``dyno-bench``; são registados
aqui com o mesmo status (registo idempotente) porque os endpoints do dano os devolvem
antes de o pacote ``dyno`` publicar o seu ``errors.py``.
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = ["DAMAGE_CODES", "DamageError"]

DAMAGE_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("FORENSIC_REPORT_NOT_FOUND", 404, "Laudo forense não encontrado"),
    ("FORENSIC_REPORT_PENDING", 409, "Laudo forense em geração"),
    ("DAMAGE_CONFIG_INVALID", 422, "Configuração do modelo de dano inválida"),
    ("DAMAGE_MODEL_UNAVAILABLE", 503, "Modelo de dano indisponível"),
    ("DAMAGE_DT_MISMATCH", 500, "Passo de tempo do dano incoerente"),
    ("DAMAGE_SNAPSHOT_INVALID", 422, "Snapshot do dano inválido"),
    ("DAMAGE_INPUT_INVALID", 500, "Entrada do modelo de dano inválida"),
    ("DAMAGE_FUEL_CHANGE_WHILE_RUNNING", 409, "Troca de combustível com o motor em marcha"),
)

_DYNO_SHARED_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("SESSION_NOT_FOUND", 404, "Sessão não encontrada"),
    ("RUN_NOT_FOUND", 404, "Puxada não encontrada"),
    ("RUN_IN_PROGRESS", 409, "Puxada em andamento"),
    ("SESSION_CLOSED", 409, "Sessão encerrada"),
    ("ENGINE_DESTROYED", 409, "Motor destruído"),
)

for _code, _status, _title in DAMAGE_CODES + _DYNO_SHARED_CODES:
    register_error(_code, _status, _title)


class DamageError(SimRemapError):
    """Erro do modelo de dano; use ``DamageError(detail, code="DAMAGE_...")``."""

    code = "DAMAGE_INPUT_INVALID"
    status = 500
    title = "Entrada do modelo de dano inválida"

    @property
    def damage_code(self) -> str:
        """Código efetivo do erro (``error_code``)."""
        return self.error_code
