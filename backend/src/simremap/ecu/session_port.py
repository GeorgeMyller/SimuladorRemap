"""Porta "session registry" usada por ``POST /api/v1/sessions/{session_id}/calibration`` (E-20).

O ecu-core não conhece o dyno-bench: o endpoint fala com uma implementação desta
porta, publicada pelo dono das sessões em ``app.state.ecu_session_port`` (ou injetada
nos testes por um fake). Sem porta instalada não há sessões: E-20 devolve 404
``SESSION_NOT_FOUND``.

O que o dyno-bench deve fornecer
--------------------------------
1. ``get_session(session_id)``: ``SessionCalibrationInfo`` com ``vehicle_id``,
   ``profile_id`` (perfil de ECU ativo), ``run_active`` (puxada em ``arming``,
   ``running``, ``steady_state_hold`` ou ``coastdown``: decide o modo
   ``live_tables``), ``initial_calibration_id`` (``simulation_session.calibration_id``),
   ``initial_calibration_version`` (versão carregada no arranque; base do diff do 1.º
   aplicar) e ``t_sim_s``; ``None`` se a sessão não existir ou estiver encerrada.
2. ``apply_calibration(session_id, command)``: envia ``command.to_command()`` (tipo
   ``calibration.apply``, simulation-bus 3.6) ao worker e devolve o ``applied_t_sim_s``
   quando chegar a saída ``ack`` com o mesmo ``request_id``. O worker trata o comando
   com ``simremap.ecu.apply.handle_apply_command`` (compila e chama
   ``EcuRuntime.swap_calibration`` na fronteira de tick). Fila cheia: lançar
   ``SimRemapError(code="SIM_WORKER_BUSY")``.
3. ``cancel_apply(session_id, request_id)``: chamado pelo ecu-core quando a confirmação
   não chega em 100 ms (EC-08); o worker deve descartar o comando pendente com esse
   ``request_id`` para que nenhum tick use a versão nova.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

__all__ = [
    "APPLY_COMMAND_TYPE",
    "CalibrationApplyCommand",
    "SessionCalibrationInfo",
    "SessionRegistryPort",
]

APPLY_COMMAND_TYPE = "calibration.apply"


@dataclass(frozen=True, slots=True)
class SessionCalibrationInfo:
    """Estado da sessão relevante para aplicar uma calibração."""

    session_id: str
    vehicle_id: str
    profile_id: str
    run_active: bool
    initial_calibration_id: str | None = None
    t_sim_s: float = 0.0
    # Versão com que a sessão arrancou (``simulation_session.active_calibration_version``);
    # ``None`` ⇒ a última versão da calibração inicial (compatibilidade).
    initial_calibration_version: int | None = None


@dataclass(frozen=True, slots=True)
class CalibrationApplyCommand:
    """Comando ``calibration.apply`` para o worker (serializável: só tipos JSON)."""

    request_id: str
    session_id: str
    calibration_id: str
    version: int
    content_hash: str
    mode: Literal["full", "live_tables"]
    payload_json: str  # CalibrationContent canónico (JSON); o worker recompila

    def to_command(self) -> dict[str, object]:
        return {
            "type": APPLY_COMMAND_TYPE,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "calibration_id": self.calibration_id,
            "version": self.version,
            "content_hash": self.content_hash,
            "mode": self.mode,
            "payload_json": self.payload_json,
        }


@runtime_checkable
class SessionRegistryPort(Protocol):
    async def get_session(self, session_id: str) -> SessionCalibrationInfo | None: ...

    async def apply_calibration(self, session_id: str, command: CalibrationApplyCommand) -> float:
        """Entrega o comando e devolve ``applied_t_sim_s`` após o ``ack`` do worker."""
        ...

    async def cancel_apply(self, session_id: str, request_id: str) -> None: ...
