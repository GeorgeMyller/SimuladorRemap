"""Casos de uso de E-23 a E-25: swap de ECU e configuração base (RF-13, RF-17 a RF-21, RF-27).

Fluxo do swap (``swap_ecu``):

1. sessão pela ``ProfileSessionPort`` (404 ``SESSION_NOT_FOUND``, 409 ``SESSION_CLOSED``,
   409 ``RUN_IN_PROGRESS``); perfil alvo ativo (404 ``ECU_PROFILE_NOT_FOUND``);
2. idempotência por ``request_id`` (10 min);
3. ``plan_swap`` (422 ``SWAP_TARGET_INVALID``/``SWAP_CONFIRMATION_REQUIRED``/
   ``SWAP_NOT_SUPPORTED_FOR_VEHICLE``); snapshot da calibração OEM ativa;
4. calibração do destino: snapshot OEM, calibração standalone guardada ou mapa base novo
   pelo assistente (criado pelo ecu-core com ``metadata.source = wizard``);
5. comando ``ecu.swap`` ao worker com confirmação em ≤ 100 ms (504
   ``CALIBRATION_APPLY_TIMEOUT``, nada muda);
6. estado gravado numa transação (``ecu_session_state``), ``session_calibration``
   atualizada e guarda de partida atualizada.

``put_base_setup``: base só editável fora do OEM (409 ``BASE_SETUP_NOT_EDITABLE_OEM``),
concorrência otimista (409 ``BASE_SETUP_VERSION_CONFLICT``), versão imutável nova,
mapa base pelo assistente (``generate_base_map``), limites convertidos em estratégias
(nova versão da calibração com ``change_summary`` "base-setup vN: limites", RF-27), troca
do modo de injeção do ``ft-pro`` (RF-14). Timeout do worker ⇒ base gravada, estado
``awaiting_base_setup`` com ``base_map`` em ``invalid`` e 504 (EC-05).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final

from simremap.ecu.calibration import (
    CONTENT_FIELDS,
    Calibration,
    CalibrationContent,
    CalibrationMetadata,
    canonical_json,
)
from simremap.ecu.repository import CalibrationRepository
from simremap.ecu.service import stock_calibration_id, validate_with_profile
from simremap.profiles.contracts import (
    BaseSetup,
    BaseSetupResult,
    BaseSetupUpdate,
    EcuProfileId,
    EcuState,
    OemSnapshot,
    SwapRequest,
    SwapResult,
    VehicleEcuHardware,
    WizardInputs,
)
from simremap.profiles.errors import profile_error
from simremap.profiles.hardware import (
    default_vehicle_hardware,
    hardware_sheet,
    load_vehicle_hardware,
)
from simremap.profiles.hooks.standalone import protection_strategies
from simremap.profiles.registry import ProfileRegistry
from simremap.profiles.repository import EcuSessionState, ProfileRepository
from simremap.profiles.session_port import EcuSessionInfo, EcuSwapCommand, ProfileSessionPort
from simremap.profiles.setup import (
    BaseMapStatus,
    ProfileSessionGuard,
    SessionSetupState,
    build_checklist,
    hardware_config,
    oem_base_setup,
    pending_items,
    prefill_base_setup,
    setup_hash,
    validate_base_setup,
)
from simremap.profiles.swap import SwapIdempotency, plan_swap, state_after_setup
from simremap.profiles.wizard import WizardResult, generate_base_map, switch_fuel_model_mode

if TYPE_CHECKING:
    from collections.abc import Callable

    from simremap.catalog.contracts import FuelSpec, VehicleSpec
    from simremap.catalog.service import CatalogService
    from simremap.core.errors import SimRemapError

__all__ = ["SWAP_ACK_TIMEOUT_S", "ProfileService"]

SWAP_ACK_TIMEOUT_S: Final = 0.1  # s, confirmação do worker (rest-api 1.3, EC-05)


@dataclass(slots=True)
class _Ctx:
    info: EcuSessionInfo
    state: EcuSessionState
    vehicle: VehicleSpec
    hardware: VehicleEcuHardware
    hardware_file: bool
    stock_fuel: FuelSpec


@dataclass(slots=True)
class _MapOutcome:
    calibration: Calibration | None = None
    wizard: WizardResult | None = None
    warnings: list[str] = field(default_factory=list)


def _payload(cal: CalibrationContent) -> str:
    return canonical_json(cal.model_dump(mode="json", include=set(CONTENT_FIELDS)))


class ProfileService:
    """Orquestra porta da sessão, repositórios, registo, catálogo e guarda."""

    def __init__(
        self,
        *,
        port: ProfileSessionPort | None,
        repo: ProfileRepository,
        calibrations: CalibrationRepository,
        registry: ProfileRegistry,
        catalog: CatalogService,
        guard: ProfileSessionGuard,
        idempotency: SwapIdempotency,
        profile_enabled: Callable[[str], bool] | None = None,
        ack_timeout_s: float = SWAP_ACK_TIMEOUT_S,
    ) -> None:
        self.port = port
        self.repo = repo
        self.calibrations = calibrations
        self.registry = registry
        self.catalog = catalog
        self.guard = guard
        self.idempotency = idempotency
        self.profile_enabled = profile_enabled or (lambda _pid: True)
        self.ack_timeout_s = ack_timeout_s

    # ------------------------------------------------------------------ contexto

    async def _context(self, session_id: str) -> _Ctx:
        info = await self.port.get_session(session_id) if self.port is not None else None
        if info is None:
            raise profile_error(
                "SESSION_NOT_FOUND", f"A sessão {session_id} não existe.", session_id=session_id
            )
        if info.closed:
            raise profile_error(
                "SESSION_CLOSED", f"A sessão {session_id} está encerrada.", session_id=session_id
            )
        vehicle = self.catalog.get_vehicle(info.vehicle_id)
        hw_file = load_vehicle_hardware(info.vehicle_id)
        state = await self.repo.get_state(session_id)
        if state is None:
            family = self.registry.family(info.profile_id)
            state = EcuSessionState(
                session_id=session_id,
                profile_id=info.profile_id,
                ecu_state="oem" if family == "oem" else "awaiting_base_setup",
            )
        return _Ctx(
            info=info,
            state=state,
            vehicle=vehicle,
            hardware=hw_file or default_vehicle_hardware(vehicle),
            hardware_file=hw_file is not None,
            stock_fuel=self.catalog.get_fuel(vehicle.stock_fuel_id),
        )

    @staticmethod
    def _no_run(ctx: _Ctx) -> None:
        if ctx.info.run_active:
            raise profile_error(
                "RUN_IN_PROGRESS",
                "Há uma puxada em andamento; aguarde o fim ou aborte-a.",
                session_id=ctx.info.session_id,
            )

    def _resolve_enabled(self, profile_id: str) -> EcuProfileId:
        pid = self.registry.resolve(profile_id)
        if not self.profile_enabled(pid.value):
            raise profile_error(
                "ECU_PROFILE_NOT_FOUND",
                f"O perfil de ECU {pid.value} não está ativo.",
                profile_id=pid.value,
            )
        return pid

    async def _latest_base(self, session_id: str) -> tuple[int | None, BaseSetup | None]:
        latest = await self.repo.get_base(session_id)
        return (latest.version, latest.base_setup) if latest is not None else (None, None)

    async def _active_calibration(self, ctx: _Ctx) -> Calibration | None:
        active = await self.calibrations.get_session_calibration(ctx.info.session_id)
        if active is not None:
            return await self.calibrations.get(active.calibration_id, active.version)
        for cal_id in (
            ctx.info.initial_calibration_id,
            stock_calibration_id(ctx.vehicle.vehicle_id, ctx.state.profile_id),
        ):
            if cal_id is not None and await self.calibrations.exists(cal_id):
                return await self.calibrations.get(cal_id)
        return None

    # ------------------------------------------------------------------ calibrações

    async def _create_wizard_map(
        self, profile_id: EcuProfileId, base: BaseSetup, ctx: _Ctx, wizard: WizardInputs | None
    ) -> _MapOutcome:
        result = generate_base_map(profile_id, base, ctx.vehicle, wizard)
        validate_with_profile(result.content, self.registry.hooks_for(profile_id.value))
        meta = CalibrationMetadata(
            name=f"Mapa base {profile_id.value} (assistente)",
            source="wizard",
            change_summary="mapa base gerado pelo assistente",
            extra={"base_setup_hash": setup_hash(base)},
        )
        cal = await self.calibrations.create(result.content, meta)
        return _MapOutcome(calibration=cal, wizard=result, warnings=list(result.warnings))

    async def _new_version(
        self, cal: Calibration, content: CalibrationContent, summary: str, base: BaseSetup
    ) -> Calibration:
        validate_with_profile(content, self.registry.hooks_for(cal.profile_id.value))
        meta = cal.metadata.model_copy(
            update={
                "source": "wizard",
                "change_summary": summary,
                "extra": {**cal.metadata.extra, "base_setup_hash": setup_hash(base)},
            }
        )
        return await self.calibrations.replace(cal.calibration_id, cal.version, content, meta)

    # ------------------------------------------------------------------ worker

    async def _send(
        self,
        ctx: _Ctx,
        *,
        profile_id: str,
        ecu_state: EcuState,
        feature_package: str,
        base: BaseSetup | None,
        cal: Calibration | None,
    ) -> float | None:
        """``ecu.swap`` ao worker; ``applied_t_sim_s`` ou 504 com o comando cancelado."""
        port = self.port
        if port is None:  # pragma: no cover - _context já exige a porta
            return None
        override = ctx.state.hardware_override
        command = EcuSwapCommand(
            request_id=str(uuid.uuid4()),
            session_id=ctx.info.session_id,
            profile_id=profile_id,
            previous_profile_id=ctx.state.profile_id,
            ecu_state=ecu_state,
            feature_package=feature_package,
            base_setup_json=canonical_json(base.model_dump(mode="json")) if base else None,
            calibration_id=cal.calibration_id if cal else None,
            calibration_version=cal.version if cal else None,
            content_hash=cal.content_hash if cal else None,
            calibration_payload_json=_payload(cal) if cal else None,
            hardware_override_json=override.model_dump_json() if override else None,
        )
        try:
            applied = await asyncio.wait_for(
                port.swap_ecu(ctx.info.session_id, command), timeout=self.ack_timeout_s
            )
        except TimeoutError:
            await port.cancel_swap(ctx.info.session_id, command.request_id)
            raise self._timeout(command.request_id) from None
        if cal is not None:
            await self.calibrations.set_session_calibration(ctx.info.session_id, cal, applied)
        return applied

    def _timeout(self, request_id: str) -> SimRemapError:
        return profile_error(
            "CALIBRATION_APPLY_TIMEOUT",
            f"O simulador não confirmou a troca em {int(self.ack_timeout_s * 1000)} ms.",
            apply_request_id=request_id,
        )

    def _publish(
        self, session_id: str, state: EcuState, profile_id: str, pending: list[str]
    ) -> None:
        self.guard.update(session_id, SessionSetupState(profile_id, state, tuple(pending)))

    # ------------------------------------------------------------------ checklist

    def _base_map_status(self, state: EcuSessionState, minimum: bool) -> BaseMapStatus:
        if state.ecu_state == "standalone_ready":
            return "ok"
        if minimum and state.standalone_calibration_id is not None:
            return "invalid"  # mapa gravado sem confirmação do worker (EC-05)
        return "missing"

    # ------------------------------------------------------------------ E-23

    async def swap_ecu(self, session_id: str, req: SwapRequest) -> SwapResult:  # noqa: PLR0912, PLR0915
        ctx = await self._context(session_id)
        self._no_run(ctx)
        target = self._resolve_enabled(req.target_profile_id.value)
        cached = self.idempotency.get(session_id, req.request_id)
        if cached is not None:
            return cached
        state = ctx.state
        current_family = self.registry.family(state.profile_id)
        target_family = self.registry.family(target)
        base_version, base = await self._latest_base(session_id)
        prefilled = False
        if target_family == "standalone" and base is None and req.prefill_from_hardware_sheet:
            base = prefill_base_setup(ctx.vehicle, ctx.hardware, ctx.stock_fuel)
            base_version = None
            prefilled = True  # o usuário revê a ficha e gera o mapa no PUT da base
        new_base = base if base is not None and base_version is None else None
        if (
            base is not None
            and target == EcuProfileId.M1_RACE
            and base.feature_package != req.feature_package
        ):
            base = base.model_copy(update={"feature_package": req.feature_package})
            new_base = base
        n_cyl = ctx.vehicle.engine.n_cyl
        minimum = (
            base is not None and build_checklist(base, ctx.hardware, n_cyl=n_cyl).minimum_valid
        )
        plan_minimum = minimum and not prefilled
        stored_profile: str | None = None
        stored: Calibration | None = None
        if state.standalone_calibration_id is not None and await self.calibrations.exists(
            state.standalone_calibration_id
        ):
            stored = await self.calibrations.get(state.standalone_calibration_id)
            stored_profile = stored.profile_id.value
        plan = plan_swap(
            current_profile=state.profile_id,
            target_profile=target.value,
            current_family=current_family,
            target_family=target_family,
            confirm_snapshot=req.confirm_snapshot,
            minimum_valid=plan_minimum,
            stored_standalone_profile=stored_profile,
            swap_supported=ctx.hardware_file and ctx.hardware.swap_supported,
        )
        snapshot_id, snapshot_version = (
            state.oem_snapshot_calibration_id,
            state.oem_snapshot_version,
        )
        snapshot: OemSnapshot | None = None
        if plan.take_snapshot:
            active = await self._active_calibration(ctx)
            if active is not None:
                snapshot_id, snapshot_version = active.calibration_id, active.version
        if snapshot_id is not None and snapshot_version is not None:
            snap_cal = await self.calibrations.get(snapshot_id, snapshot_version)
            snapshot = OemSnapshot(
                calibration_id=snap_cal.calibration_id,
                version=snap_cal.version,
                content_hash=snap_cal.content_hash,
            )

        cal: Calibration | None = None
        standalone_id = state.standalone_calibration_id
        if plan.map_action == "restore_snapshot":
            if snapshot is not None:
                cal = await self.calibrations.get(snapshot.calibration_id, snapshot.version)
            else:
                stock = stock_calibration_id(ctx.vehicle.vehicle_id, target.value)
                cal = (
                    await self.calibrations.get(stock)
                    if await self.calibrations.exists(stock)
                    else None
                )
        elif plan.map_action == "reuse_standalone":
            cal = stored
        elif plan.map_action == "generate" and base is not None:
            outcome = await self._create_wizard_map(target, base, ctx, None)
            cal = outcome.calibration
            standalone_id = cal.calibration_id if cal else standalone_id
        declared = None if target_family == "oem" else base
        await self._send(
            ctx,
            profile_id=target.value,
            ecu_state=plan.ecu_state,
            feature_package=req.feature_package,
            base=declared,
            cal=cal,
        )
        new_state = replace(
            state,
            profile_id=target.value,
            ecu_state=plan.ecu_state,
            feature_package=req.feature_package,
            oem_snapshot_calibration_id=snapshot_id,
            oem_snapshot_version=snapshot_version,
            standalone_calibration_id=standalone_id,
        )
        created = await self.repo.save_state(
            new_state, new_base, base_version=state.latest_base_setup_version
        )
        if created is not None:
            new_state = replace(new_state, latest_base_setup_version=created.version)
            base_version = created.version
        if target_family == "oem":
            checklist = build_checklist(
                oem_base_setup(ctx.vehicle, ctx.hardware, ctx.stock_fuel), ctx.hardware,
                base_map="ok" if cal is not None else "missing", n_cyl=n_cyl,
            )  # fmt: skip
        else:
            checklist = build_checklist(
                base,
                ctx.hardware,
                base_map="ok" if plan.ecu_state == "standalone_ready" else "missing",
                fuel_mismatch_suspected=ctx.info.fuel_mismatch_suspected,
                n_cyl=n_cyl,
            )
        pending = pending_items(checklist) if plan.ecu_state == "awaiting_base_setup" else []
        self._publish(session_id, plan.ecu_state, target.value, pending)
        result = SwapResult(
            session_id=session_id,
            previous_profile_id=EcuProfileId(state.profile_id),
            profile_id=target,
            ecu_state=plan.ecu_state,
            oem_snapshot=snapshot,
            base_setup_version=new_state.latest_base_setup_version
            if target_family == "standalone"
            else None,
            calibration_id=cal.calibration_id if cal is not None else None,
            checklist=checklist,
            hardware_sheet=hardware_sheet(ctx.hardware, ctx.vehicle),
        )
        self.idempotency.put(session_id, req.request_id, result)
        return result

    # ------------------------------------------------------------------ E-24

    async def get_base_setup(self, session_id: str) -> BaseSetupResult:
        ctx = await self._context(session_id)
        state = ctx.state
        sheet = hardware_sheet(ctx.hardware, ctx.vehicle)
        n_cyl = ctx.vehicle.engine.n_cyl
        if self.registry.family(state.profile_id) == "oem":
            base = oem_base_setup(ctx.vehicle, ctx.hardware, ctx.stock_fuel)
            return BaseSetupResult(
                session_id=session_id,
                profile_id=EcuProfileId(state.profile_id),
                editable=False,
                ecu_state="oem",
                base_setup_version=None,
                base_setup=base,
                setup_hash=setup_hash(base),
                checklist=build_checklist(base, ctx.hardware, base_map="ok", n_cyl=n_cyl),
                hardware_sheet=sheet,
            )
        version, latest_base = await self._latest_base(session_id)
        minimum = (
            latest_base is not None
            and build_checklist(latest_base, ctx.hardware, n_cyl=n_cyl).minimum_valid
        )
        checklist = build_checklist(
            latest_base,
            ctx.hardware,
            base_map=self._base_map_status(state, minimum),
            fuel_mismatch_suspected=ctx.info.fuel_mismatch_suspected,
            n_cyl=n_cyl,
        )
        cal_version = None
        if state.ecu_state == "standalone_ready" and state.standalone_calibration_id is not None:
            cal_version = (await self.calibrations.get(state.standalone_calibration_id)).version
        return BaseSetupResult(
            session_id=session_id,
            profile_id=EcuProfileId(state.profile_id),
            editable=True,
            ecu_state=state.ecu_state,
            base_setup_version=version,
            base_setup=latest_base,
            setup_hash=setup_hash(latest_base) if latest_base is not None else None,
            checklist=checklist,
            hardware_sheet=sheet,
            calibration_id=state.standalone_calibration_id if cal_version is not None else None,
            calibration_version=cal_version,
        )

    # ------------------------------------------------------------------ E-25

    async def put_base_setup(  # noqa: PLR0915
        self, session_id: str, body: BaseSetupUpdate
    ) -> BaseSetupResult:
        ctx = await self._context(session_id)
        state = ctx.state
        if self.registry.family(state.profile_id) == "oem":
            raise profile_error(
                "BASE_SETUP_NOT_EDITABLE_OEM",
                "A configuração base do OEM-Stage é a de série e não pode ser editada.",
                profile_id=state.profile_id,
            )
        self._no_run(ctx)
        latest = state.latest_base_setup_version
        if body.base_version != latest:
            raise profile_error(
                "BASE_SETUP_VERSION_CONFLICT",
                f"A base foi alterada: versão atual {latest}, enviada {body.base_version}.",
                latest_version=latest,
                base_version=body.base_version,
            )
        base = body.base_setup
        n_cyl = ctx.vehicle.engine.n_cyl
        validate_base_setup(base, n_cyl)
        pid = EcuProfileId(state.profile_id)
        _, previous = await self._latest_base(session_id)
        minimum = build_checklist(base, ctx.hardware, n_cyl=n_cyl).minimum_valid
        new_version = (latest or 0) + 1

        current: Calibration | None = None
        if state.standalone_calibration_id is not None and await self.calibrations.exists(
            state.standalone_calibration_id
        ):
            current = await self.calibrations.get(state.standalone_calibration_id)
            if current.profile_id != pid:
                current = None
        outcome = _MapOutcome()
        if minimum and body.generate_base_map:
            outcome = await self._create_wizard_map(pid, base, ctx, body.wizard)
        elif minimum and current is not None:
            content: CalibrationContent = current
            changes: list[str] = []
            mode = body.wizard.fuel_model_mode if body.wizard is not None else None
            if mode is not None and mode != current.fuel_model.mode:
                content = switch_fuel_model_mode(content, mode, hardware_config(base, ctx.vehicle))
                changes.append(f"modo {mode}")
            limits_changed = previous is None or previous.protection != base.protection
            if body.apply_limits_to_calibration and limits_changed:
                strategies = {
                    **content.strategies,
                    **protection_strategies(
                        base.protection,
                        wideband=base.sensors.wideband is not None,
                        existing=dict(content.strategies),
                    ),
                }
                data = content.model_dump(include=set(CONTENT_FIELDS))
                data["strategies"] = {k: v.model_dump() for k, v in strategies.items()}
                content = CalibrationContent.model_validate(data)
                changes.append("limites")
            outcome.calibration = current
            if changes:
                outcome.calibration = await self._new_version(
                    current, content, f"base-setup v{new_version}: {', '.join(changes)}", base
                )
        cal = outcome.calibration if minimum else None
        ecu_state = state_after_setup(minimum_valid=minimum, has_map=cal is not None)
        standalone_id = cal.calibration_id if cal is not None else state.standalone_calibration_id
        package = base.feature_package if pid == EcuProfileId.M1_RACE else state.feature_package
        new_state = replace(
            state,
            ecu_state=ecu_state,
            standalone_calibration_id=standalone_id,
            feature_package=package,
        )
        created = await self.repo.save_state(new_state, base, base_version=latest)
        version = created.version if created is not None else new_version
        new_state = replace(new_state, latest_base_setup_version=version)
        try:
            await self._send(
                ctx,
                profile_id=pid.value,
                ecu_state=ecu_state,
                feature_package=package,
                base=base,
                cal=cal,
            )
        except Exception as exc:
            if getattr(exc, "error_code", None) == "CALIBRATION_APPLY_TIMEOUT":
                timed_out = replace(new_state, ecu_state="awaiting_base_setup")
                await self.repo.save_state(timed_out)
                self._publish(session_id, "awaiting_base_setup", pid.value, ["base_map"])
            raise
        undersized = "INJECTOR_UNDERSIZED" in outcome.warnings
        checklist = build_checklist(
            base,
            ctx.hardware,
            base_map="ok" if ecu_state == "standalone_ready" else "missing",
            fuel_mismatch_suspected=ctx.info.fuel_mismatch_suspected,
            injector_undersized=undersized,
            n_cyl=n_cyl,
        )
        pending = pending_items(checklist) if ecu_state == "awaiting_base_setup" else []
        self._publish(session_id, ecu_state, pid.value, pending)
        wiz = outcome.wizard
        return BaseSetupResult(
            session_id=session_id,
            profile_id=pid,
            editable=True,
            ecu_state=ecu_state,
            base_setup_version=version,
            base_setup=base,
            setup_hash=setup_hash(base),
            checklist=checklist,
            hardware_sheet=hardware_sheet(ctx.hardware, ctx.vehicle),
            calibration_id=cal.calibration_id if cal is not None else None,
            calibration_version=cal.version if cal is not None else None,
            estimated_peak_duty_pct=wiz.estimated_peak_duty_pct if wiz is not None else None,
            warnings=outcome.warnings,
        )

    # ------------------------------------------------------------------ guarda

    async def pending_for(self, session_id: str) -> list[str]:
        """Itens pendentes lidos do banco (alternativa assíncrona à guarda em memória)."""
        state = await self.repo.get_state(session_id)
        if state is None or state.ecu_state != "awaiting_base_setup":
            return []
        _, base = await self._latest_base(session_id)
        minimum = base is not None and build_checklist(base, None).minimum_valid
        checklist = build_checklist(base, None, base_map=self._base_map_status(state, minimum))
        return pending_items(checklist)
