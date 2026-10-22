"""Códigos de erro do telemetry-datalogger (rest-api 4.8; tel apêndice "Catálogo de code").

Os códigos HTTP entram no catálogo único (``register_error``). Os códigos só do WebSocket
(envelope ``error`` ou motivo de fecho) não têm status HTTP (coluna "—" da rest-api 4.8):
ficam em ``WS_ERROR_TITLES`` com o título do envelope e o código de fecho quando fatal.
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = [
    "CLOSE_CODES",
    "TELEMETRY_ERROR_CODES",
    "WS_ERROR_TITLES",
    "TelemetryError",
    "telemetry_error",
    "ws_title",
]

TELEMETRY_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("LOG_NOT_FOUND", 404, "Log não encontrado"),
    ("LOG_NOT_READY", 409, "Log ainda em gravação"),
    ("LOG_CORRUPTED", 500, "Log corrompido"),
    ("LOG_SCHEMA_INVALID", 422, "Log fora do schema"),
    ("LOG_FORMAT_UNSUPPORTED", 422, "Versão de log não suportada"),
    ("LOG_HASH_MISMATCH", 422, "SHA-256 do log divergente"),
    ("LOG_ALREADY_IMPORTED", 409, "Log já importado"),
    ("LOG_COMPARE_NO_OVERLAP", 422, "Logs sem faixa de rotação comum"),
    # Códigos de outros donos devolvidos pelos endpoints da telemetria (registo idempotente).
    ("RUN_NOT_FOUND", 404, "Puxada não encontrada"),
    ("VEHICLE_NOT_FOUND", 404, "Veículo não encontrado"),
)

WS_ERROR_TITLES: Final[dict[str, str]] = {
    "WS_MESSAGE_INVALID": "Mensagem inválida",
    "WS_UNKNOWN_CHANNEL": "Canal desconhecido",
    "WS_FPS_OUT_OF_RANGE": "FPS fora de 30–60",
    "WS_CYLINDER_OUT_OF_RANGE": "Cilindro fora do motor",
    "WS_RESUME_GAP": "Histórico fora do buffer de replay",
    "WS_RESUME_INVALID": "resume_from_seq inválido",
    "WS_RATE_LIMITED": "Mensagens em excesso",
    "WS_TOO_MANY_CONNECTIONS": "Conexões em excesso",
    "WS_ORIGIN_FORBIDDEN": "Origem não permitida",
    "WS_IDLE_TIMEOUT": "Conexão inativa",
    "SPECTRUM_UNAVAILABLE": "Espectro indisponível",
    "THROTTLE_LOCKED_BY_RUN": "Acelerador bloqueado pela puxada",
    "SIM_WORKER_BUSY": "Worker de simulação ocupado",
    "SIM_WORKER_UNAVAILABLE": "Worker de simulação indisponível",
    "SIM_INTERNAL_ERROR": "Erro interno no laço de simulação",
    "SESSION_NOT_FOUND": "Sessão não encontrada",
}

CLOSE_CODES: Final[dict[str, int]] = {
    "SESSION_NOT_FOUND": 4404,
    "WS_TOO_MANY_CONNECTIONS": 4429,
    "WS_ORIGIN_FORBIDDEN": 4403,
    "WS_IDLE_TIMEOUT": 4408,
    "WS_RATE_LIMITED": 1008,
    "SIM_WORKER_UNAVAILABLE": 1011,
}
"""Código de fecho do WebSocket por ``reason`` (websocket-telemetry 8)."""

for _code, _status, _title in TELEMETRY_ERROR_CODES:
    register_error(_code, _status, _title)


def ws_title(code: str) -> str:
    """Título do envelope ``error`` (o próprio ``code`` se desconhecido)."""
    return WS_ERROR_TITLES.get(code, code.replace("_", " ").capitalize()[:120])


class TelemetryError(SimRemapError):
    """Erro do telemetry-datalogger; use ``TelemetryError(detail, code="LOG_NOT_FOUND")``."""

    code = "LOG_NOT_FOUND"
    status = 404
    title = "Log não encontrado"


def telemetry_error(code: str, detail: str, **extra: object) -> TelemetryError:
    """Atalho para ``TelemetryError(detail, code=code, **extra)``."""
    error = TelemetryError(detail, code=code)
    error.extra.update(extra)
    return error
