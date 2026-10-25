"""Aplicação atómica de uma versão de calibração a uma sessão.

Fontes: ecu-core RF-27, RF-28; EC-07, EC-08, EC-11.

Lado da API (``apply_to_session``):

1. sessão pela ``SessionRegistryPort`` (404 ``SESSION_NOT_FOUND``);
2. calibração e versão (404 ``CALIBRATION_NOT_FOUND``/``CALIBRATION_VERSION_NOT_FOUND``);
3. veículo e perfil iguais aos da sessão (422 ``CALIBRATION_VEHICLE_MISMATCH``/
   ``CALIBRATION_PROFILE_MISMATCH``) e validação do hook do perfil;
4. ``diff`` contra a calibração ativa (no 1.º aplicar, a versão com que a sessão
   arrancou, ``initial_calibration_version``): com puxada ativa só células de tabelas
   live-tunable (sem eixos, estratégias, ``fuel_model`` nem ``profile_params``); senão
   409 ``TABLE_NOT_LIVE_TUNABLE`` com ``items`` e a calibração ativa não muda (premissa
   OQ-04: o estado de puxada vem da porta);
5. comando ``calibration.apply`` ao worker com confirmação em ≤ 100 ms; sem ``ack`` o
   pedido é cancelado e devolve 504 ``CALIBRATION_APPLY_TIMEOUT`` (nenhum tick usa a
   versão nova);
6. grava ``session_calibration`` (fonte de verdade da calibração ativa, D-10).

Reaplicar a versão já ativa é idempotente: ``changed_tables = []`` sem novo comando.

Lado do worker (``handle_apply_command``): recompila o ``payload_json`` e chama
``EcuRuntime.swap_calibration`` (troca na fronteira do tick seguinte).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Final, Literal

from simremap.ecu.calibration import (
    CONTENT_FIELDS,
    ApplyCalibrationRequest,
    ApplyCalibrationResult,
    Calibration,
    CalibrationContent,
    canonical_json,
    diff_calibrations,
)
from simremap.ecu.compiled import compile_calibration
from simremap.ecu.errors import ecu_error
from simremap.ecu.hooks import ProfileHooks
from simremap.ecu.repository import CalibrationRepository
from simremap.ecu.runtime import EcuRuntime
from simremap.ecu.service import validate_with_profile
from simremap.ecu.session_port import (
    APPLY_COMMAND_TYPE,
    CalibrationApplyCommand,
    SessionRegistryPort,
)

__all__ = ["APPLY_TIMEOUT_S", "apply_to_session", "handle_apply_command"]

APPLY_TIMEOUT_S: Final = 3.0  # s, confirmação do worker (tolerante em hosts de baixo consumo como Raspberry Pi)


def _content_payload(cal: CalibrationContent) -> str:
    return canonical_json(cal.model_dump(mode="json", include=set(CONTENT_FIELDS)))


async def apply_to_session(
    *,
    session_id: str,
    request: ApplyCalibrationRequest,
    port: SessionRegistryPort | None,
    repo: CalibrationRepository,
    hooks: ProfileHooks,
    timeout_s: float = APPLY_TIMEOUT_S,
) -> ApplyCalibrationResult:
    info = await port.get_session(session_id) if port is not None else None
    if info is None or port is None:
        raise ecu_error(
            "SESSION_NOT_FOUND", f"A sessão {session_id} não existe.", session_id=session_id
        )
    cal = await repo.get(request.calibration_id, request.version)
    if cal.vehicle_id != info.vehicle_id:
        raise ecu_error(
            "CALIBRATION_VEHICLE_MISMATCH",
            f"A calibração é do veículo {cal.vehicle_id}; a sessão usa {info.vehicle_id}.",
            calibration_vehicle_id=cal.vehicle_id,
            session_vehicle_id=info.vehicle_id,
        )
    if cal.profile_id.value != info.profile_id:
        raise ecu_error(
            "CALIBRATION_PROFILE_MISMATCH",
            f"A calibração é do perfil {cal.profile_id.value}; a sessão usa {info.profile_id}.",
            calibration_profile_id=cal.profile_id.value,
            session_profile_id=info.profile_id,
        )
    validate_with_profile(cal, hooks, request.profile_options)

    state = await repo.get_session_calibration(session_id)
    mode: Literal["full", "live_tables"] = "live_tables" if info.run_active else "full"
    if (
        state is not None
        and state.calibration_id == cal.calibration_id
        and state.version == cal.version
    ):
        return ApplyCalibrationResult(
            session_id=session_id,
            calibration_id=cal.calibration_id,
            version=cal.version,
            content_hash=cal.content_hash,
            mode=mode,
            changed_tables=[],
            applied_t_sim_s=state.applied_t_sim_s,
        )
    active: Calibration | None = None
    if state is not None:
        active = await repo.get(state.calibration_id, state.version)
    elif info.initial_calibration_id is not None and await repo.exists(info.initial_calibration_id):
        # 1.º aplicar da sessão: a base é a versão carregada no arranque (B2), não a última.
        active = await repo.get(info.initial_calibration_id, info.initial_calibration_version)
    if active is not None:
        diff = diff_calibrations(active, cal)
        changed = diff.changed_tables
        if info.run_active and not diff.live_compatible:
            raise ecu_error(
                "TABLE_NOT_LIVE_TUNABLE",
                "Durante a puxada só células de tabelas live-tunable podem mudar: "
                + ", ".join(diff.not_live),
                items=diff.not_live,
            )
    else:
        if info.run_active:
            raise ecu_error(
                "TABLE_NOT_LIVE_TUNABLE",
                "Sem calibração ativa conhecida não é possível ajustar ao vivo durante a puxada.",
                items=["calibration"],
            )
        changed = sorted(cal.tables)

    command = CalibrationApplyCommand(
        request_id=str(uuid.uuid4()),
        session_id=session_id,
        calibration_id=cal.calibration_id,
        version=cal.version,
        content_hash=cal.content_hash,
        mode=mode,
        payload_json=_content_payload(cal),
    )
    try:
        applied = await asyncio.wait_for(
            port.apply_calibration(session_id, command), timeout=timeout_s
        )
    except TimeoutError:
        await port.cancel_apply(session_id, command.request_id)
        raise ecu_error(
            "CALIBRATION_APPLY_TIMEOUT",
            f"O worker não confirmou a troca em {int(timeout_s * 1000)} ms; nada foi aplicado.",
            apply_request_id=command.request_id,
        ) from None
    await repo.set_session_calibration(session_id, cal, applied)
    return ApplyCalibrationResult(
        session_id=session_id,
        calibration_id=cal.calibration_id,
        version=cal.version,
        content_hash=cal.content_hash,
        mode=mode,
        changed_tables=changed,
        applied_t_sim_s=applied,
    )


def handle_apply_command(runtime: EcuRuntime, command: dict[str, object]) -> dict[str, object]:
    """Trata ``calibration.apply`` no worker e devolve o envelope ``ack`` (sem ``applied_t_sim_s``).

    A troca entra no próximo ``step()``; o dyno-bench completa ``applied_t_sim_s`` com o
    ``t_sim_s`` desse tick (``runtime.applied_t_sim_s``) antes de publicar o ``ack``.
    """
    if command.get("type") != APPLY_COMMAND_TYPE:
        raise ValueError("comando não é calibration.apply")
    payload = command.get("payload_json")
    if not isinstance(payload, str):
        raise ValueError("payload_json ausente")
    content = CalibrationContent.model_validate_json(payload)
    version = command.get("version")
    mode = command.get("mode")
    compiled = compile_calibration(
        content,
        runtime.n_cyl,
        calibration_id=str(command.get("calibration_id")),
        version=version if isinstance(version, int) else 1,
        content_hash=str(command.get("content_hash")),
    )
    runtime.swap_calibration(compiled, "live_tables" if mode == "live_tables" else "full")
    return {
        "type": "ack",
        "command": APPLY_COMMAND_TYPE,
        "request_id": command.get("request_id"),
        "calibration_id": compiled.calibration_id,
        "version": compiled.version,
        "content_hash": compiled.content_hash,
    }
