"""Códigos de erro do dyno-bench (rest-api 4.4; D-14, D-REST-01, D-REST-06).

Os códigos ``SESSION_NOT_FOUND``, ``RUN_NOT_FOUND``, ``RUN_IN_PROGRESS``,
``SESSION_CLOSED`` e ``ENGINE_DESTROYED`` também são registados pelo dano e pela ECU com
o mesmo status (registo idempotente). ``ECU_SETUP_INCOMPLETE`` pertence ao
``ecu-profiles``; é registado aqui com o status do dono porque o ``POST .../runs`` o
devolve pela ``ProfileSessionGuard``.

``THROTTLE_LOCKED_BY_RUN`` e ``SIM_INTERNAL_ERROR`` só existem no canal WebSocket
(envelope ``error``); não têm status HTTP e por isso não entram no catálogo HTTP.
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = [
    "DYNO_ERROR_CODES",
    "WS_ONLY_CODES",
    "DynoError",
    "dyno_error",
]

DYNO_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("SESSION_NOT_FOUND", 404, "Sessão não encontrada"),
    ("SESSION_CLOSED", 409, "Sessão encerrada"),
    ("RUN_NOT_FOUND", 404, "Puxada não encontrada"),
    ("RUN_IN_PROGRESS", 409, "Puxada em andamento"),
    ("RUN_NOT_ACTIVE", 409, "Puxada não está ativa"),
    ("ENGINE_DESTROYED", 409, "Motor destruído"),
    ("RPM_RANGE_INVALID", 422, "Faixa de rotação inválida"),
    ("GEAR_NOT_AVAILABLE", 422, "Marcha indisponível no veículo"),
    ("PROBE_NOT_ALLOWED", 422, "Sonda não permitida nesta sessão"),
    ("PHYSICS_UNAVAILABLE", 503, "Física indisponível"),
    ("ECU_SETUP_INCOMPLETE", 409, "Setup da ECU incompleto"),
    ("UPGRADES_LOCKED", 409, "Peças bloqueadas nesta sessão"),
)

WS_ONLY_CODES: Final[dict[str, str]] = {
    "THROTTLE_LOCKED_BY_RUN": "Acelerador bloqueado pela puxada",
    "SIM_INTERNAL_ERROR": "Erro interno no laço de simulação",
}
"""Códigos só do WebSocket (``code`` → ``title`` do envelope ``error``)."""

for _code, _status, _title in DYNO_ERROR_CODES:
    register_error(_code, _status, _title)


class DynoError(SimRemapError):
    """Erro do dyno-bench; use ``DynoError(detail, code="RUN_IN_PROGRESS")``."""

    code = "SESSION_NOT_FOUND"
    status = 404
    title = "Sessão não encontrada"


def dyno_error(code: str, detail: str, **extra: object) -> DynoError:
    """Atalho para ``DynoError(detail, code=code, **extra)``."""
    error = DynoError(detail, code=code)
    error.extra.update(extra)
    return error
