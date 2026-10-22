"""Porta "sessão de ECU" usada por E-23 a E-25 (swap e ``GET``/``PUT .../ecu/base-setup``).

O ecu-profiles não conhece o dyno-bench: os endpoints falam com uma implementação desta
porta publicada pelo dono das sessões em ``app.state.profiles_session_port`` (ou
injetada nos testes por um fake). Sem porta instalada não há sessões: os endpoints
devolvem 404 ``SESSION_NOT_FOUND``.

O que o dyno-bench deve fornecer
--------------------------------
1. ``get_session(session_id)``: ``EcuSessionInfo`` com ``vehicle_id``, ``profile_id``
   (perfil de ECU ativo; ``SimulationSession.profile_id``), ``run_active`` (puxada em
   ``arming``, ``running``, ``steady_state_hold`` ou ``coastdown``), ``closed``
   (sessão encerrada ⇒ 409 ``SESSION_CLOSED``), ``initial_calibration_id``
   (``simulation_session.calibration_id``), ``t_sim_s`` e ``fuel_mismatch_suspected``
   (``ProfiledEcu.fuel_mismatch_suspected`` do worker, para o item ``fuel.type`` do
   checklist); ``None`` se a sessão não existir.
2. ``swap_ecu(session_id, command)``: envia ``command.to_command()`` (tipo ``ecu.swap``,
   simulation-bus 3.6) ao worker e devolve o ``applied_t_sim_s`` quando chegar a saída
   ``ack`` com o mesmo ``request_id``. O worker trata o comando com
   ``simremap.profiles.worker.handle_swap_command`` (monta o ``ProfiledEcu`` com o perfil,
   o estado, a base declarada, a calibração e o ``HardwareOverride``) e o instala na
   fronteira de tick com o motor parado ou em cortes totais. O dyno-bench atualiza
   ``SimulationSession.profile_id`` e ``SimulationSession.ecu_state`` (D-REST-06; o valor
   persistido fica em ``ecu_session_state``) e grava ``session_calibration`` quando o
   comando traz calibração. Fila cheia: ``SimRemapError(code="SIM_WORKER_BUSY")``.
3. ``cancel_swap(session_id, request_id)``: chamado quando o ``ack`` não chega no prazo
   (100 ms, EC-05); o worker descarta o comando pendente.

O guard de partida (``ProfileSessionGuard.can_start_run``, D-REST-06) fica em
``app.state.profiles_guard``: o dyno-bench chama-o antes de aceitar ``POST .../runs`` e
responde 409 ``ECU_SETUP_INCOMPLETE`` com ``pending``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from simremap.profiles.contracts import EcuState

__all__ = ["SWAP_COMMAND_TYPE", "EcuSessionInfo", "EcuSwapCommand", "ProfileSessionPort"]

SWAP_COMMAND_TYPE = "ecu.swap"


@dataclass(frozen=True, slots=True)
class EcuSessionInfo:
    """Estado da sessão relevante para o perfil de ECU."""

    session_id: str
    vehicle_id: str
    profile_id: str
    run_active: bool = False
    closed: bool = False
    initial_calibration_id: str | None = None
    t_sim_s: float = 0.0
    fuel_mismatch_suspected: bool = False


@dataclass(frozen=True, slots=True)
class EcuSwapCommand:
    """Comando ``ecu.swap`` para o worker (só tipos JSON).

    ``base_setup_json``: ``BaseSetup`` declarada (JSON canônico) ou ``None`` (OEM, ou
    standalone sem base). ``calibration_payload_json``: ``CalibrationContent`` a compilar
    ou ``None`` (motor sem mapa: cortes totais). ``hardware_override_json``: defeito
    oculto do training-scenarios (nunca exposto pela API).
    """

    request_id: str
    session_id: str
    profile_id: str
    previous_profile_id: str
    ecu_state: EcuState
    feature_package: str = "base"
    base_setup_json: str | None = None
    calibration_id: str | None = None
    calibration_version: int | None = None
    content_hash: str | None = None
    calibration_payload_json: str | None = None
    hardware_override_json: str | None = None

    def to_command(self) -> dict[str, object]:
        return {
            "type": SWAP_COMMAND_TYPE,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "previous_profile_id": self.previous_profile_id,
            "ecu_state": self.ecu_state,
            "feature_package": self.feature_package,
            "base_setup_json": self.base_setup_json,
            "calibration_id": self.calibration_id,
            "calibration_version": self.calibration_version,
            "content_hash": self.content_hash,
            "calibration_payload_json": self.calibration_payload_json,
            "hardware_override_json": self.hardware_override_json,
        }


@runtime_checkable
class ProfileSessionPort(Protocol):
    async def get_session(self, session_id: str) -> EcuSessionInfo | None: ...

    async def swap_ecu(self, session_id: str, command: EcuSwapCommand) -> float:
        """Entrega o comando e devolve ``applied_t_sim_s`` após o ``ack`` do worker."""
        ...

    async def cancel_swap(self, session_id: str, request_id: str) -> None: ...
