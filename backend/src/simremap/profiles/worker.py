"""Lado do worker dos comandos do ecu-profiles (simulation-bus 3.6).

- ``handle_swap_command``: trata ``ecu.swap`` montando um ``ProfiledEcu`` novo com o
  perfil, o estado de ECU, a base declarada, a calibração e o ``HardwareOverride``;
  devolve o ``ProfiledEcu`` (o dyno-bench troca-o na fronteira de tick) e o envelope
  ``ack`` (o dyno-bench completa ``applied_t_sim_s`` com o ``t_sim_s`` desse tick).
- ``handle_apply_command``: ``calibration.apply`` sobre o runtime do ``ProfiledEcu``
  (delegado ao ecu-core); sem runtime (motor sem mapa) o comando é recusado.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from simremap.ecu.apply import handle_apply_command as ecu_handle_apply
from simremap.ecu.calibration import CalibrationContent
from simremap.profiles.adapter import ProfiledEcu, build_profiled_ecu
from simremap.profiles.contracts import BaseSetup, EcuState, HardwareOverride
from simremap.profiles.registry import ProfileRegistry
from simremap.profiles.session_port import SWAP_COMMAND_TYPE

if TYPE_CHECKING:
    from simremap.catalog.contracts import FuelSpec, VehicleSpec

__all__ = ["handle_apply_command", "handle_swap_command"]

_STATES: tuple[EcuState, ...] = ("oem", "awaiting_base_setup", "standalone_ready")


def _opt_str(command: dict[str, object], key: str) -> str | None:
    value = command.get(key)
    return value if isinstance(value, str) else None


def handle_swap_command(
    command: dict[str, object],
    *,
    vehicle: VehicleSpec,
    stock_fuel: FuelSpec,
    enabled_strategies: frozenset[str] | None = None,
    registry: ProfileRegistry | None = None,
) -> tuple[ProfiledEcu, dict[str, object]]:
    if command.get("type") != SWAP_COMMAND_TYPE:
        raise ValueError("comando não é ecu.swap")
    state = command.get("ecu_state")
    if state not in _STATES:
        raise ValueError("ecu_state inválido")
    ecu_state: EcuState = state
    base_json = _opt_str(command, "base_setup_json")
    cal_json = _opt_str(command, "calibration_payload_json")
    ov_json = _opt_str(command, "hardware_override_json")
    version = command.get("calibration_version")
    profiled = build_profiled_ecu(
        vehicle=vehicle,
        stock_fuel=stock_fuel,
        profile_id=str(command.get("profile_id")),
        ecu_state=ecu_state,
        base_setup=BaseSetup.model_validate_json(base_json) if base_json else None,
        calibration=CalibrationContent.model_validate_json(cal_json) if cal_json else None,
        calibration_id=_opt_str(command, "calibration_id") or "uncompiled",
        calibration_version=version if isinstance(version, int) else 1,
        content_hash=_opt_str(command, "content_hash"),
        override=HardwareOverride.model_validate_json(ov_json) if ov_json else None,
        enabled_strategies=enabled_strategies,
        registry=registry,
    )
    ack: dict[str, object] = {
        "type": "ack",
        "command": SWAP_COMMAND_TYPE,
        "request_id": command.get("request_id"),
        "profile_id": profiled.profile_id.value,
        "ecu_state": profiled.ecu_state,
        "calibration_id": _opt_str(command, "calibration_id"),
    }
    return profiled, ack


def handle_apply_command(profiled: ProfiledEcu, command: dict[str, object]) -> dict[str, object]:
    """``calibration.apply`` no runtime do perfil (troca na próxima fronteira de tick)."""
    if profiled.runtime is None:
        raise ValueError("ECU sem runtime (setup incompleto): use ecu.swap com calibração")
    return ecu_handle_apply(profiled.runtime, command)
