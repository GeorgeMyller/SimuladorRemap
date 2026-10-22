"""Códigos de erro do training-scenarios (rest-api 4.9; D-16, D-REST-04, D-REST-09).

Códigos HTTP registados no catálogo único (``register_error``). Os códigos internos
(``TRACE_UNAVAILABLE``, ``PROBE_FAILED``, ``EVALUATION_INTERRUPTED``,
``DAMAGE_MODEL_UNAVAILABLE`` em ``Evaluation.error_code`` e ``BASELINE_FAILED`` no estado
da tentativa) não têm status HTTP e ficam em ``INTERNAL_CODES``.

Códigos de outros donos devolvidos pelos endpoints dos cenários (``VEHICLE_NOT_FOUND``,
``CALIBRATION_NOT_FOUND``, ``SIM_CAPACITY_EXCEEDED``, ``RUN_IN_PROGRESS``,
``STORAGE_FULL``, ``PAYLOAD_TOO_LARGE``) são usados com o registo do dono.
"""

from __future__ import annotations

from typing import Final

from simremap.core.errors import SimRemapError, register_error

__all__ = [
    "INTERNAL_CODES",
    "SCENARIO_ERROR_CODES",
    "ScenarioError",
    "scenario_error",
]

SCENARIO_ERROR_CODES: Final[tuple[tuple[str, int, str], ...]] = (
    ("PLAYER_PROFILE_REQUIRED", 400, "Perfil de jogador obrigatório"),
    ("PLAYER_PROFILE_NOT_FOUND", 404, "Perfil de jogador não encontrado"),
    ("NICKNAME_TAKEN", 409, "Nickname já usado"),
    ("PROFILE_LIMIT_REACHED", 409, "Limite de perfis atingido"),
    ("INSTRUCTOR_ROLE_REQUIRED", 403, "Ação exclusiva do instrutor"),
    ("SCENARIO_NOT_FOUND", 404, "Cenário não encontrado"),
    ("SCENARIO_ALREADY_EXISTS", 409, "Cenário já existe"),
    ("SCENARIO_INVALID", 422, "Cenário inválido"),
    ("SCENARIO_CALIBRATION_HASH_MISMATCH", 422, "Hash da calibração inicial divergente"),
    ("SCENARIO_VERSION_MISMATCH", 409, "Versão do cenário divergente"),
    ("ATTEMPT_NOT_FOUND", 404, "Tentativa não encontrada"),
    ("ATTEMPT_NOT_OWNED", 403, "Tentativa de outro perfil"),
    ("ATTEMPT_NOT_IN_PROGRESS", 409, "Tentativa não está em andamento"),
    ("ATTEMPT_NOT_EVALUATED", 409, "Tentativa sem avaliação"),
    ("HINT_LOCKED", 409, "Dica ainda bloqueada"),
    ("HINTS_EXHAUSTED", 409, "Sem dicas restantes"),
    ("SUBMISSION_LIMIT_REACHED", 409, "Limite de submissões atingido"),
    ("CALIBRATION_NOT_IN_ATTEMPT", 422, "Calibração fora da tentativa"),
    ("EVALUATION_NOT_FOUND", 404, "Avaliação não encontrada"),
    ("REPLAY_VERSION_INCOMPATIBLE", 409, "Versão incompatível para replay"),
    ("PACKAGE_HASH_MISMATCH", 422, "SHA-256 do pacote inválido"),
    ("PACKAGE_FORMAT_UNSUPPORTED", 422, "Formato de pacote não suportado"),
    ("PACKAGE_MALFORMED", 422, "Pacote malformado"),
    ("PACKAGE_SCHEMA_INVALID", 422, "Pacote fora do schema"),
    ("PACKAGE_NOT_CANONICALIZABLE", 422, "Pacote não canonicalizável"),
    ("CALIBRATION_SERVICE_UNAVAILABLE", 503, "Serviço de calibração indisponível"),
    ("PACKAGE_SERVICE_UNAVAILABLE", 503, "Serviço de pacotes indisponível"),
)

INTERNAL_CODES: Final[dict[str, str]] = {
    "TRACE_UNAVAILABLE": "Log da puxada ilegível após 3 tentativas",
    "PROBE_FAILED": "Sonda de knock terminou com falha interna",
    "BASELINE_FAILED": "Puxada base abortada ou fora do prazo de 120 s",
    "EVALUATION_INTERRUPTED": "Avaliação pendente interrompida por reinício",
    "DAMAGE_MODEL_UNAVAILABLE": "Modelo de dano indisponível",
}
"""Códigos sem resposta HTTP (``Evaluation.error_code`` e ``Attempt.failure_code``)."""

for _code, _status, _title in SCENARIO_ERROR_CODES:
    register_error(_code, _status, _title)


class ScenarioError(SimRemapError):
    """Erro do training-scenarios; use ``scenario_error(code, detail, **extra)``."""

    code = "SCENARIO_NOT_FOUND"
    status = 404
    title = "Cenário não encontrado"


def scenario_error(code: str, detail: str, **extra: object) -> ScenarioError:
    """Atalho para ``ScenarioError(detail, code=code)`` com campos extra no ``ProblemDetail``."""
    error = ScenarioError(detail, code=code)
    error.extra.update(extra)
    return error
