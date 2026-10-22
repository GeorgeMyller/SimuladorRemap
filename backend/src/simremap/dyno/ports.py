"""Adaptadores das portas que outros componentes consomem das sessões do dyno-bench.

- ``DynoEcuSessionPort`` → ``simremap.ecu.session_port.SessionRegistryPort``
  (``app.state.ecu_session_port``): estado da sessão para o ``POST .../calibration`` (E-20)
  e entrega do ``calibration.apply`` ao worker com ``applied_t_sim_s`` do ``ack``.
- ``DynoDamagePort`` → ``simremap.damage.session_port.DamageSessionPort``
  (``app.state.damage_port``): ``SessionView``, puxadas, saúde ao vivo (``engine.health``),
  ``engine.restore`` e pesos das bielas para E-12 a E-14.
- ``DynoProfileSessionPort`` → ``simremap.profiles.session_port.ProfileSessionPort``
  (``app.state.profiles_session_port``): sessão vista pelo ecu-profiles e entrega do
  ``ecu.swap`` ao worker (``SimulationSession.profile_id``/``ecu_state`` atualizados no ``ack``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from simremap.core.errors import SimRemapError
from simremap.damage.contracts import EngineHealth
from simremap.damage.session_port import SessionView
from simremap.dyno.contracts import DynoRun
from simremap.dyno.session import (
    CalibrationApplied,
    DynoService,
    ResolvedCalibration,
    SessionRuntime,
)
from simremap.ecu.calibration import CalibrationContent
from simremap.ecu.session_port import CalibrationApplyCommand, SessionCalibrationInfo

__all__ = ["DynoDamagePort", "DynoEcuSessionPort", "DynoProfileSessionPort"]

HEALTH_TIMEOUT_S: Final = 0.5
RESTORE_TIMEOUT_S: Final = 2.0
APPLY_TIMEOUT_S: Final = 1.0
INFO_TIMEOUT_S: Final = 0.2


def _active(service: DynoService, session_id: str) -> SessionRuntime | None:
    rt = service.runtime(session_id)
    if rt is None or rt.view.state == "closed" or rt.closing:
        return None
    return rt


class DynoEcuSessionPort:
    """``SessionRegistryPort`` do ecu-core sobre o ``DynoService``."""

    def __init__(self, service: DynoService) -> None:
        self.service = service

    async def get_session(self, session_id: str) -> SessionCalibrationInfo | None:
        rt = _active(self.service, session_id)
        if rt is None:
            return None
        return SessionCalibrationInfo(
            session_id=session_id,
            vehicle_id=rt.view.vehicle_id,
            profile_id=rt.view.profile_id,
            run_active=rt.view.active_run_id is not None,
            initial_calibration_id=rt.view.calibration_id,
            t_sim_s=rt.view.t_sim_s,
            initial_calibration_version=rt.initial_calibration_version,
        )

    async def apply_calibration(self, session_id: str, command: CalibrationApplyCommand) -> float:
        rt = _active(self.service, session_id)
        if rt is None:
            raise SimRemapError(f"A sessão {session_id} não existe.", code="SESSION_NOT_FOUND")
        ack = await self.service.request(rt, command.to_command(), APPLY_TIMEOUT_S)
        if not ack.get("ok", False):
            raise SimRemapError(
                f"O worker recusou a calibração: {ack.get('detail', ack.get('code'))}",
                code="VALIDATION_FAILED",
            )
        applied = ack.get("applied_t_sim_s")
        t_applied = float(applied) if isinstance(applied, int | float) else rt.view.t_sim_s
        content = CalibrationContent.model_validate_json(command.payload_json)
        rt.activate_calibration(
            ResolvedCalibration(
                calibration_id=command.calibration_id,
                version=command.version,
                vehicle_id=rt.view.vehicle_id,
                profile_id=rt.view.profile_id,
                content=content,
                content_hash=command.content_hash,
            )
        )
        await self.service.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        self.service.notify_calibration_applied(
            CalibrationApplied(
                session_id=session_id,
                t_sim_s=t_applied,
                calibration_id=command.calibration_id,
                content_hash=command.content_hash,
                kind="calibration.apply",
                profile_id=rt.view.profile_id,
            )
        )
        return t_applied

    async def cancel_apply(self, session_id: str, request_id: str) -> None:
        rt = _active(self.service, session_id)
        if rt is None:
            return
        await self.service.send(rt, {"type": "calibration.cancel", "request_id": request_id})


class DynoDamagePort:
    """``DamageSessionPort`` do knock-and-failure-model sobre o ``DynoService``."""

    def __init__(self, service: DynoService) -> None:
        self.service = service

    async def get_session(self, session_id: str) -> SessionView | None:
        rt = self.service.runtime(session_id)
        if rt is not None:
            v = rt.view
            return SessionView(
                session_id=session_id,
                vehicle_id=v.vehicle_id,
                state=v.state,
                damage_enabled=v.damage_enabled,
                active_run_id=v.active_run_id,
                t_sim_s=v.t_sim_s,
                last_forensic_report_url=rt.last_forensic_report_url,
            )
        stored = await self.service.repo.get_session(session_id)
        if stored is None:
            return None
        return SessionView(
            session_id=session_id,
            vehicle_id=stored.vehicle_id,
            state=stored.state,
            damage_enabled=stored.damage_enabled,
            t_sim_s=stored.t_sim_s,
        )

    async def get_run(self, run_id: str) -> DynoRun | None:
        return await self.service.find_run(run_id)

    async def live_health(self, session_id: str, include_failures: bool) -> EngineHealth | None:
        rt = _active(self.service, session_id)
        if rt is None or rt.worker_failed:
            return None
        try:
            ack = await self.service.request(
                rt,
                {"type": "engine.health", "include_failures": include_failures},
                HEALTH_TIMEOUT_S,
            )
        except (TimeoutError, asyncio.CancelledError, SimRemapError):
            return None
        health = ack.get("health")
        if not ack.get("ok") or health is None:
            return None
        weights = ack.get("rod_weights")
        if isinstance(weights, list):
            rt.rod_weights = [float(w) for w in weights]
        return EngineHealth.model_validate(health).model_copy(
            update={"last_forensic_report_url": rt.last_forensic_report_url}
        )

    async def restore_engine(self, session_id: str, note: str | None) -> EngineHealth:
        rt = _active(self.service, session_id)
        if rt is None or rt.worker_failed:
            raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
        try:
            ack = await self.service.request(
                rt, {"type": "engine.restore", "note": note}, RESTORE_TIMEOUT_S
            )
        except TimeoutError:
            raise SimRemapError(
                "O worker não confirmou a restauração do motor.", code="SIM_WORKER_UNAVAILABLE"
            ) from None
        if not ack.get("ok"):
            raise SimRemapError(
                f"A puxada {rt.view.active_run_id} está em andamento.", code="RUN_IN_PROGRESS"
            )
        rt.update(engine_locked=False, state="ready")
        await self.service.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        weights = ack.get("rod_weights")
        if isinstance(weights, list):
            rt.rod_weights = [float(w) for w in weights]
        return EngineHealth.model_validate(ack["health"]).model_copy(
            update={"last_forensic_report_url": rt.last_forensic_report_url}
        )

    async def rod_weights(self, session_id: str) -> list[float]:
        rt = self.service.runtime(session_id)
        return [] if rt is None else list(rt.rod_weights)


class DynoProfileSessionPort:
    """``ProfileSessionPort`` do ecu-profiles sobre o ``DynoService``."""

    def __init__(self, service: DynoService) -> None:
        self.service = service

    async def get_session(self, session_id: str) -> Any:
        from simremap.profiles.session_port import EcuSessionInfo  # noqa: PLC0415

        rt = self.service.runtime(session_id)
        if rt is None:
            stored = await self.service.repo.get_session(session_id)
            if stored is None:
                return None
            return EcuSessionInfo(
                session_id=session_id,
                vehicle_id=stored.vehicle_id,
                profile_id=stored.profile_id,
                closed=stored.state == "closed",
                initial_calibration_id=stored.calibration_id,
                t_sim_s=stored.t_sim_s,
            )
        mismatch = False
        if not rt.worker_failed and not rt.closing:
            try:
                ack = await self.service.request(rt, {"type": "ecu.info"}, INFO_TIMEOUT_S)
                mismatch = bool(ack.get("fuel_mismatch_suspected", False))
            except (TimeoutError, SimRemapError):
                mismatch = False
        v = rt.view
        return EcuSessionInfo(
            session_id=session_id,
            vehicle_id=v.vehicle_id,
            profile_id=v.profile_id,
            run_active=v.active_run_id is not None,
            closed=v.state == "closed" or rt.closing,
            initial_calibration_id=v.calibration_id,
            t_sim_s=v.t_sim_s,
            fuel_mismatch_suspected=mismatch,
        )

    async def swap_ecu(self, session_id: str, command: Any) -> float:
        rt = _active(self.service, session_id)
        if rt is None:
            raise SimRemapError(f"A sessão {session_id} não existe.", code="SESSION_NOT_FOUND")
        ack = await self.service.request(rt, command.to_command(), APPLY_TIMEOUT_S)
        if not ack.get("ok", False):
            raise SimRemapError(
                f"O worker recusou a troca de ECU: {ack.get('detail', ack.get('code'))}",
                code="VALIDATION_FAILED",
            )
        changes: dict[str, Any] = {"profile_id": str(ack.get("profile_id", command.profile_id))}
        state = ack.get("ecu_state", command.ecu_state)
        if state in ("oem", "awaiting_base_setup", "standalone_ready"):
            changes["ecu_state"] = state
        rt.update(**changes)
        if command.calibration_payload_json and command.calibration_id and command.content_hash:
            rt.activate_calibration(
                ResolvedCalibration(
                    calibration_id=command.calibration_id,
                    version=command.calibration_version or 1,
                    vehicle_id=rt.view.vehicle_id,
                    profile_id=rt.view.profile_id,
                    content=CalibrationContent.model_validate_json(
                        command.calibration_payload_json
                    ),
                    content_hash=command.content_hash,
                )
            )
        await self.service.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        applied = ack.get("applied_t_sim_s")
        t_applied = float(applied) if isinstance(applied, int | float) else rt.view.t_sim_s
        if command.calibration_id and command.content_hash:
            self.service.notify_calibration_applied(
                CalibrationApplied(
                    session_id=session_id,
                    t_sim_s=t_applied,
                    calibration_id=str(command.calibration_id),
                    content_hash=str(command.content_hash),
                    kind="ecu.swap",
                    profile_id=rt.view.profile_id,
                )
            )
        return t_applied

    async def cancel_swap(self, session_id: str, request_id: str) -> None:
        rt = _active(self.service, session_id)
        if rt is None:
            return
        await self.service.send(rt, {"type": "ecu.swap.cancel", "request_id": request_id})
