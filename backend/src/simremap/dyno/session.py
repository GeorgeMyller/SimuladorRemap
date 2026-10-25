"""Gestor de sessões e puxadas no event loop (dyno RF-01, RF-02, RF-17, RF-20 a RF-23, RF-25; D-31).

``DynoService`` (``app.state.dyno_service``):

- ``create_session``: limite ``max_active_sessions`` (409 ``SIM_CAPACITY_EXCEEDED`` com o
  ``session_id`` ativo no ``detail``), veículo do catálogo (404 ``VEHICLE_NOT_FOUND``,
  409 ``VEHICLE_NOT_VALIDATED``), combustível (409 ``FUEL_NOT_ALLOWED``), perfil
  (404 ``ECU_PROFILE_NOT_FOUND``), calibração (404 ``CALIBRATION_NOT_FOUND``, 422
  ``CALIBRATION_VEHICLE_MISMATCH``), ``seed`` sorteada em 0..2^63−1 quando omitida,
  ``physics_faults`` validadas contra o veículo; arranca o ``DynoSimTask`` no
  ``SimWorkerHost`` e grava ``simulation_session``. Sem ``calibration_id`` a sessão
  trabalha num clone da calibração de série (``source = user``, nome "Sessão <veículo>
  <perfil>"; 002 D-04). ``upgrades`` (422 ``UPGRADE_NOT_COMPATIBLE``) modificam o veículo
  antes dos limites estruturais, da ECU e da física; ``ethanol_pct`` monta o combustível
  ``flex`` a partir de E27 e E100 (409 ``FUEL_NOT_ALLOWED`` sem os dois no veículo) e
  loga ``session.upgrades_applied``;
- ``install_upgrades``: troca as peças da oficina com a sessão viva (sem puxada, fora de
  tentativas de cenário: 409 ``UPGRADES_LOCKED``); o worker remonta física e dano
  (``hardware.install``) e a calibração ativa continua. Loga ``session.upgrades_installed``;
- ``start_run``/``abort_run``: guardas de ``dyno.guards``, ``run.start``/``run.abort`` pela
  fila de comandos do worker;
- ``delete_session``: aborta a puxada ativa (``session_closed``), para o worker e liberta o
  slot;
- ``get_run``: memória da sessão ou banco; curva bruta ou suavizada na leitura.

As saídas do worker são consumidas por ``dyno.output_router.OutputRouter`` (uma tarefa
por sessão) e publicadas no ``dyno.stream.StreamHub``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.catalog.contracts import FuelSpec, VehicleSpec
from simremap.catalog.errors import FuelNotAllowed
from simremap.catalog.upgrades import UpgradePackage, UpgradeResult, apply_upgrades
from simremap.core.errors import SimRemapError, is_registered
from simremap.core.logging import get_logger
from simremap.damage.mechanical import StructuralLimits
from simremap.dyno.assembly import DynoInitPayload
from simremap.dyno.contracts import (
    SEED_RANDOM_MAX,
    TERMINAL_RUN_STATES,
    AbortReason,
    DynoRun,
    DynoRunRequest,
    RunState,
    SessionCreateRequest,
    SimulationSession,
)
from simremap.dyno.curve import smooth_curve
from simremap.dyno.errors import dyno_error
from simremap.dyno.guards import ProfileSessionGuard, RunGuardInput, check_run_allowed
from simremap.dyno.repository import DynoRepository
from simremap.dyno.stream import SessionStream, StreamHub
from simremap.ecu.calibration import CalibrationContent, compute_content_hash, parse_content
from simremap.ecu.contracts import EcuValidationError
from simremap.ecu.service import stock_calibration_id
from simremap.physics.config import resolve_config
from simremap.physics.contracts import PhysicsConfig
from simremap.physics.fuel_blend import blend_fuel

if TYPE_CHECKING:
    from simremap.core.worker.host import SimWorkerHost, WorkerHandle
    from simremap.damage.service import ForensicService
    from simremap.dyno.output_router import OutputRouter

__all__ = [
    "SESSION_CALIBRATION_NAME",
    "TASK_SPEC",
    "CalibrationApplied",
    "CalibrationCloner",
    "CalibrationListener",
    "CalibrationSource",
    "CatalogVehicleSource",
    "DynoService",
    "RepositoryCalibrationSource",
    "ResolvedCalibration",
    "SessionRuntime",
    "VehicleSource",
    "draw_session_seed",
    "new_run_id",
]

log = get_logger("simremap.dyno")

TASK_SPEC: Final = "simremap.dyno.runner:DynoSimTask"
ACK_TIMEOUT_S: Final = 2.0
INSTALL_TIMEOUT_S: Final = 10.0  # remontagem da física + 1 s de marcha lenta no worker
RUN_RESULT_TIMEOUT_S: Final = 5.0
CLOSE_TIMEOUT_S: Final = 1.0
MONITOR_INTERVAL_S: Final = 1.0
REALTIME_DEGRADED_FACTOR: Final = 0.5
REALTIME_DEGRADED_SAMPLES: Final = 5
_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SESSION_CALIBRATION_NAME: Final = "Sessão {vehicle} {profile}"
FLEX_ANCHOR_FUELS: Final = ("e27", "e100")
STALE_SESSION_MAX_AGE_S: Final = 600.0  # s, 10 min ocioso sem puxada nem clientes


def draw_session_seed() -> int:
    """Semente sorteada pelo servidor em [0, 2^53 − 1] (``Number.MAX_SAFE_INTEGER`` do JS)."""
    return secrets.randbelow(SEED_RANDOM_MAX + 1)


def new_run_id(now: datetime | None = None) -> str:
    """ULID (48 bits de milissegundos + 80 bits aleatórios, Crockford base32)."""
    moment = now or datetime.now(UTC)
    millis = int(moment.timestamp() * 1000) & ((1 << 48) - 1)
    value = (millis << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


@dataclass(frozen=True, slots=True)
class CalibrationApplied:
    """Calibração aplicada numa sessão (``calibration.apply`` ou ``ecu.swap`` com ``ack`` ok)."""

    session_id: str
    t_sim_s: float  # applied_t_sim_s do ack (fronteira de tick no worker)
    calibration_id: str
    content_hash: str
    kind: Literal["calibration.apply", "ecu.swap"] = "calibration.apply"
    profile_id: str | None = None


CalibrationListener = Callable[[CalibrationApplied], None]
"""Ouvinte síncrono e rápido (ex.: auditoria V-03 do training-scenarios)."""


# --------------------------------------------------------------------------- fontes


class VehicleSource(Protocol):
    """Catálogo visto pelo dyno (substituível nos testes por ``app.state.dyno_vehicle_source``)."""

    def vehicle_for_session(self, vehicle_id: str) -> VehicleSpec: ...
    def fuel_for_vehicle(self, vehicle_id: str, fuel_id: str) -> FuelSpec: ...
    def catalog_sha256(self) -> str: ...
    def factory_calibration(self, vehicle_id: str, profile_id: str) -> dict[str, Any] | None: ...


class CatalogVehicleSource:
    """``VehicleSource`` sobre ``simremap.catalog.service.get_catalog()``."""

    def _service(self) -> Any:
        from simremap.catalog.service import get_catalog

        return get_catalog()

    def vehicle_for_session(self, vehicle_id: str) -> VehicleSpec:
        spec: VehicleSpec = self._service().get_for_session(vehicle_id)
        return spec

    def fuel_for_vehicle(self, vehicle_id: str, fuel_id: str) -> FuelSpec:
        fuel: FuelSpec = self._service().get_fuel_for_vehicle(vehicle_id, fuel_id)
        return fuel

    def catalog_sha256(self) -> str:
        return str(self._service().catalog_sha256)

    def factory_calibration(self, vehicle_id: str, profile_id: str) -> dict[str, Any] | None:
        try:
            payload: dict[str, Any] = self._service().get_factory_calibration_payload(
                vehicle_id, profile_id
            )
        except SimRemapError:
            return None
        return payload


@dataclass(frozen=True, slots=True)
class ResolvedCalibration:
    """Calibração usada pela sessão (conteúdo + identidade + hash)."""

    calibration_id: str
    version: int
    vehicle_id: str
    profile_id: str
    content: CalibrationContent
    content_hash: str


class CalibrationSource(Protocol):
    async def resolve(
        self, calibration_id: str, vehicle_id: str, profile_id: str
    ) -> ResolvedCalibration | None: ...


@runtime_checkable
class CalibrationCloner(Protocol):
    """Fonte que grava um clone da calibração para a sessão (002 D-04)."""

    async def clone_for_session(
        self, cal: ResolvedCalibration, name: str
    ) -> ResolvedCalibration | None: ...


class RepositoryCalibrationSource:
    """Calibração do ``ecu-core`` (banco) com fallback para a de fábrica do catálogo."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession] | None,
        vehicles: VehicleSource,
    ) -> None:
        self._maker = sessionmaker
        self._vehicles = vehicles

    async def resolve(
        self, calibration_id: str, vehicle_id: str, profile_id: str
    ) -> ResolvedCalibration | None:
        if self._maker is not None:
            from simremap.ecu.repository import CalibrationRepository

            async with self._maker() as db:
                repo = CalibrationRepository(db)
                if await repo.exists(calibration_id):
                    cal = await repo.get(calibration_id)
                    return ResolvedCalibration(
                        calibration_id=cal.calibration_id,
                        version=cal.version,
                        vehicle_id=cal.vehicle_id,
                        profile_id=cal.profile_id.value,
                        content=cal.content(),
                        content_hash=cal.content_hash,
                    )
        if calibration_id != stock_calibration_id(vehicle_id, profile_id):
            return None
        payload = self._vehicles.factory_calibration(vehicle_id, profile_id)
        if payload is None:
            return None
        try:
            content = parse_content({**payload, "vehicle_id": vehicle_id, "profile_id": profile_id})
        except EcuValidationError as exc:
            raise SimRemapError(
                f"A calibração de fábrica {calibration_id} é inválida ({exc.code}).",
                code=exc.code if is_registered(exc.code) else "VALIDATION_FAILED",
                calibration_id=calibration_id,
            ) from exc
        return ResolvedCalibration(
            calibration_id=calibration_id,
            version=int(payload.get("version", 1)),
            vehicle_id=vehicle_id,
            profile_id=profile_id,
            content=content,
            content_hash=compute_content_hash(content),
        )

    async def clone_for_session(
        self, cal: ResolvedCalibration, name: str
    ) -> ResolvedCalibration | None:
        """Grava ``cal`` como calibração nova do usuário (``None`` sem banco)."""
        if self._maker is None:
            return None
        from simremap.ecu.calibration import CalibrationMetadata
        from simremap.ecu.repository import CalibrationRepository

        async with self._maker() as db:
            created = await CalibrationRepository(db).create(
                cal.content, CalibrationMetadata(name=name[:80], source="user")
            )
        return ResolvedCalibration(
            calibration_id=created.calibration_id,
            version=created.version,
            vehicle_id=created.vehicle_id,
            profile_id=created.profile_id.value,
            content=created.content(),
            content_hash=created.content_hash,
        )


# --------------------------------------------------------------------------- runtime


@dataclass(eq=False)
class SessionRuntime:
    """Estado vivo de uma sessão no event loop."""

    view: SimulationSession
    handle: WorkerHandle
    stream: SessionStream
    vehicle: VehicleSpec
    calibration: ResolvedCalibration
    data_version: int
    catalog_sha256: str
    steps_per_tick: int = 1
    initial_calibration_version: int | None = None  # versão carregada na criação (B2, T031)
    runs: dict[str, DynoRun] = field(default_factory=dict)
    run_done: dict[str, asyncio.Future[DynoRun]] = field(default_factory=dict)
    acks: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    traces: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    run_events: dict[str, set[str]] = field(default_factory=dict)
    rod_weights: list[float] = field(default_factory=list)
    last_forensic_report_url: str | None = None
    router_task: asyncio.Task[None] | None = None
    monitor_task: asyncio.Task[None] | None = None
    close_task: asyncio.Task[None] | None = None  # fecho único partilhado (idempotente)
    worker_failed: bool = False
    closing: bool = False
    low_rtf_samples: int = 0
    spectrum_available: bool = False  # session.ready: amostrador com bind_spectrum

    @property
    def session_id(self) -> str:
        return self.view.session_id

    def update(self, **changes: Any) -> None:
        self.view = self.view.model_copy(update=changes)

    def activate_calibration(self, calibration: ResolvedCalibration) -> None:
        """Calibração em uso pelo worker; espelhada em ``view.active_calibration_*`` (T031)."""
        self.calibration = calibration
        self.update(
            active_calibration_id=calibration.calibration_id,
            active_calibration_version=calibration.version,
        )

    @property
    def active_run(self) -> DynoRun | None:
        rid = self.view.active_run_id
        return None if rid is None else self.runs.get(rid)


class DynoService:
    """Sessões, puxadas, portas e persistência do dyno-bench."""

    def __init__(
        self,
        host: SimWorkerHost,
        *,
        repository: DynoRepository,
        vehicles: VehicleSource,
        calibrations: CalibrationSource,
        streams: StreamHub | None = None,
        forensic: ForensicService | None = None,
        profile_guard: Callable[[], ProfileSessionGuard | None] | ProfileSessionGuard | None = None,
        profile_enabled: Any = None,
        enabled_strategies: list[str] | None = None,
        task_options: Mapping[str, Any] | None = None,
        fps: int = 50,
    ) -> None:
        self.host = host
        self.repo = repository
        self.vehicles = vehicles
        self.calibrations = calibrations
        self.streams = streams or StreamHub()
        self.forensic = forensic
        self._profile_guard = profile_guard
        self._profile_enabled = profile_enabled
        self.enabled_strategies = enabled_strategies
        self.task_options = dict(task_options or {})
        self.fps = fps
        self._sessions: dict[str, SessionRuntime] = {}
        self._create_lock = asyncio.Lock()
        self._calibration_listeners: list[CalibrationListener] = []

    # ------------------------------------------------------------------ ouvintes
    def add_calibration_listener(self, listener: CalibrationListener) -> Callable[[], None]:
        """Regista um ouvinte de ``calibration.apply``/``ecu.swap`` (idempotente).

        Chamado depois do ``ack`` ok do worker, com o ``applied_t_sim_s``. Devolve a função
        que remove o ouvinte.
        """
        if listener not in self._calibration_listeners:
            self._calibration_listeners.append(listener)

        def remove() -> None:
            self.remove_calibration_listener(listener)

        return remove

    def remove_calibration_listener(self, listener: CalibrationListener) -> None:
        with contextlib.suppress(ValueError):
            self._calibration_listeners.remove(listener)

    def notify_calibration_applied(self, event: CalibrationApplied) -> None:
        """Entrega ``event`` aos ouvintes; falha de um ouvinte não afeta a aplicação."""
        for listener in tuple(self._calibration_listeners):
            try:
                listener(event)
            except Exception as exc:
                log.warning(
                    "dyno.calibration_listener_failed",
                    session_id=event.session_id,
                    detail=f"{type(exc).__name__}: {exc}"[:200],
                )

    @property
    def profile_guard(self) -> ProfileSessionGuard | None:
        """Guarda do ecu-profiles (resolvida a cada uso: o router dele arranca depois)."""
        guard = self._profile_guard
        if guard is None or isinstance(guard, ProfileSessionGuard):
            return guard
        return guard()

    # ------------------------------------------------------------------ consulta
    @property
    def active_sessions(self) -> list[str]:
        return [sid for sid, rt in self._sessions.items() if rt.view.state != "closed"]

    def runtime(self, session_id: str) -> SessionRuntime | None:
        return self._sessions.get(session_id)

    def require(self, session_id: str) -> SessionRuntime:
        rt = self._sessions.get(session_id)
        if rt is None:
            raise dyno_error(
                "SESSION_NOT_FOUND", f"A sessão {session_id} não existe.", session_id=session_id
            )
        return rt

    async def get_session(self, session_id: str) -> SimulationSession:
        rt = self._sessions.get(session_id)
        if rt is not None:
            return rt.view
        stored = await self.repo.get_session(session_id)
        if stored is None:
            raise dyno_error(
                "SESSION_NOT_FOUND", f"A sessão {session_id} não existe.", session_id=session_id
            )
        return stored

    # ------------------------------------------------------------------ criação
    def _check_profile(self, profile_id: str) -> None:
        check = self._profile_enabled
        if check is not None and not check(profile_id):
            raise SimRemapError(
                f"O perfil de ECU {profile_id} não está habilitado.", code="ECU_PROFILE_NOT_FOUND"
            )

    async def create_session(self, request: SessionCreateRequest) -> SimulationSession:
        async with self._create_lock:
            active = self.active_sessions
            if len(active) >= self.host.max_active_sessions:
                for sid in list(active):
                    rt = self._sessions.get(sid)
                    if rt is not None and (
                        rt.worker_failed or rt.view.state == "closed" or rt.closing
                    ):
                        with contextlib.suppress(Exception):
                            await self._close(rt, AbortReason.SESSION_CLOSED)
                active = self.active_sessions
            if len(active) >= self.host.max_active_sessions:
                now_utc = datetime.now(UTC)
                for sid in list(active):
                    rt = self._sessions.get(sid)
                    if (
                        rt is not None
                        and rt.stream.subscribers == 0
                        and rt.view.active_run_id is None
                        and (now_utc - rt.view.created_at).total_seconds() > STALE_SESSION_MAX_AGE_S
                    ):
                        age_s = round((now_utc - rt.view.created_at).total_seconds(), 1)
                        log.info("dyno.reclaim_stale_session", session_id=sid, age_s=age_s)
                        with contextlib.suppress(Exception):
                            await self._close(rt, AbortReason.SESSION_CLOSED)
                        break
                active = self.active_sessions
            if len(active) >= self.host.max_active_sessions:
                raise SimRemapError(
                    f"Limite de {self.host.max_active_sessions} sessão(ões) ativa(s) atingido; "
                    f"sessão ativa: {', '.join(active)}.",
                    code="SIM_CAPACITY_EXCEEDED",
                    active_session_ids=active,
                )
            return await self._create(request)

    def _session_fuel(self, vehicle: VehicleSpec, request: SessionCreateRequest) -> FuelSpec:
        """Combustível efetivo: do catálogo ou ``flex`` (blend E27/E100, 002 RF-18)."""
        if request.ethanol_pct is None:
            return self.vehicles.fuel_for_vehicle(
                vehicle.vehicle_id, request.fuel_id or vehicle.stock_fuel_id
            )
        missing = [f for f in FLEX_ANCHOR_FUELS if f not in vehicle.allowed_fuel_ids]
        if missing:
            raise FuelNotAllowed(
                f"O veículo {vehicle.vehicle_id} não aceita flex: faltam "
                f"{', '.join(missing)} nos combustíveis permitidos.",
                vehicle_id=vehicle.vehicle_id,
                fuel_id="flex",
                allowed_fuel_ids=list(vehicle.allowed_fuel_ids),
            )
        vid = vehicle.vehicle_id
        e27, e100 = (self.vehicles.fuel_for_vehicle(vid, f) for f in FLEX_ANCHOR_FUELS)
        return blend_fuel(e27, e100, request.ethanol_pct)

    async def _session_calibration(
        self, vehicle: VehicleSpec, request: SessionCreateRequest
    ) -> ResolvedCalibration:
        """Calibração pedida, ou um clone da de série quando ``calibration_id`` é omitido."""
        calibration_id = request.calibration_id or (
            vehicle.stock_calibration_id
            if request.profile_id == vehicle.stock_profile_id
            else stock_calibration_id(vehicle.vehicle_id, request.profile_id)
        )
        cal = await self.calibrations.resolve(
            calibration_id, vehicle.vehicle_id, request.profile_id
        )
        if cal is None:
            raise SimRemapError(
                f"A calibração {calibration_id} não existe.", code="CALIBRATION_NOT_FOUND"
            )
        if cal.vehicle_id != vehicle.vehicle_id:
            raise SimRemapError(
                f"A calibração é do veículo {cal.vehicle_id}; a sessão usa {vehicle.vehicle_id}.",
                code="CALIBRATION_VEHICLE_MISMATCH",
            )
        if cal.profile_id != request.profile_id:
            raise SimRemapError(
                f"A calibração é do perfil {cal.profile_id}; a sessão usa {request.profile_id}.",
                code="CALIBRATION_PROFILE_MISMATCH",
            )
        if request.calibration_id is not None or not isinstance(
            self.calibrations, CalibrationCloner
        ):
            return cal
        name = SESSION_CALIBRATION_NAME.format(
            vehicle=vehicle.display_name, profile=request.profile_id
        )
        return await self.calibrations.clone_for_session(cal, name) or cal

    def _log_upgrades(
        self, session_id: str, request: SessionCreateRequest, upgraded: UpgradeResult
    ) -> None:
        if request.upgrades.is_stock and request.ethanol_pct is None:
            return
        log.info(
            "session.upgrades_applied",
            session_id=session_id,
            vehicle_id=request.vehicle_id,
            upgrades=request.upgrades.non_stock(),
            exhaust_backpressure_scale=upgraded.physics.exhaust_backpressure_scale,
            fuel_pump_capacity_scale=upgraded.physics.fuel_pump_capacity_scale,
            ethanol_pct=request.ethanol_pct,
        )

    async def _create(self, request: SessionCreateRequest) -> SimulationSession:
        catalog_vehicle = self.vehicles.vehicle_for_session(request.vehicle_id)
        fuel = self._session_fuel(catalog_vehicle, request)
        self._check_profile(request.profile_id)
        upgraded = apply_upgrades(catalog_vehicle, request.upgrades)
        vehicle = upgraded.vehicle
        overrides = upgraded.physics
        cal = await self._session_calibration(vehicle, request)
        seed = request.seed if request.seed is not None else draw_session_seed()
        configured_hz = os.environ.get("SIMREMAP_SIM_HZ")
        max_hz = int(configured_hz) if configured_hz and configured_hz.isdigit() else request.sim_hz
        sim_hz = min(request.sim_hz, max_hz)
        # Validação antecipada contra o veículo (sem esperar o setup do worker).
        resolve_config(
            PhysicsConfig(
                sim_hz=sim_hz,
                seed=seed,
                faults=list(request.physics_faults),
                exhaust_backpressure_scale=overrides.exhaust_backpressure_scale,
                fuel_pump_capacity_scale=overrides.fuel_pump_capacity_scale,
            ),
            vehicle,
            fuel,
        )
        StructuralLimits.from_vehicle(vehicle)
        session_id = uuid.uuid4().hex
        options = dict(self.task_options)
        payload = DynoInitPayload(
            session_id=session_id,
            seed=seed,
            sim_hz=sim_hz,
            vehicle=vehicle,
            fuel=fuel,
            calibration=cal.content,
            calibration_id=cal.calibration_id,
            calibration_version=cal.version,
            calibration_hash=cal.content_hash,
            profile_id=request.profile_id,
            ecu_state="oem" if request.profile_id == "oem-stage" else "standalone_ready",
            stock_fuel=self.vehicles.fuel_for_vehicle(vehicle.vehicle_id, vehicle.stock_fuel_id),
            enabled_strategies=self.enabled_strategies,
            ambient=request.ambient,
            rig=request.rig,
            correction_standard=request.correction_standard,
            operator_protection=request.operator_protection,
            egt_abort_enabled=request.egt_abort_enabled,
            damage_enabled=request.damage_enabled,
            physics_faults=list(request.physics_faults),
            exhaust_backpressure_scale=overrides.exhaust_backpressure_scale,
            fuel_pump_capacity_scale=overrides.fuel_pump_capacity_scale,
            ethanol_pct=request.ethanol_pct,
            fps=self.fps,
            attempt_id=request.attempt_id,
            **options,
        )
        view = SimulationSession(
            **request.model_dump(exclude={"seed", "calibration_id", "fuel_id", "sim_hz"}),
            session_id=session_id,
            seed=seed,
            sim_hz=sim_hz,
            calibration_id=cal.calibration_id,
            active_calibration_id=cal.calibration_id,
            active_calibration_version=cal.version,
            fuel_id=fuel.fuel_id,
            state="ready",
            created_at=datetime.now(UTC),
        )
        handle = await self.host.start_session(
            session_id, TASK_SPEC, payload.model_dump_json().encode("utf-8"), sim_hz=sim_hz
        )
        catalog_sha = self.vehicles.catalog_sha256()
        stored = await self.repo.save_session(
            view, data_version=vehicle.data_version, catalog_sha256=catalog_sha
        )
        if not stored and self.repo.available:
            await self.host.stop_session(session_id)
            raise SimRemapError(
                "Banco de dados indisponível ao criar a sessão.",
                code="DATABASE_UNAVAILABLE",
                headers={"Retry-After": "2"},
            )
        rt = SessionRuntime(
            view=view,
            handle=handle,
            stream=self.streams.create(session_id),
            vehicle=vehicle,
            calibration=cal,
            data_version=vehicle.data_version,
            catalog_sha256=catalog_sha,
            steps_per_tick=payload.steps_per_tick,
            initial_calibration_version=cal.version,
        )
        self._sessions[session_id] = rt
        from simremap.dyno.output_router import OutputRouter

        router: OutputRouter = OutputRouter(self, rt)
        rt.router_task = asyncio.create_task(router.run(), name=f"dyno-output-{session_id}")
        rt.monitor_task = asyncio.create_task(self._monitor(rt), name=f"dyno-monitor-{session_id}")
        self._log_upgrades(session_id, request, upgraded)
        log.info(
            "dyno.session_created",
            session_id=session_id,
            vehicle_id=vehicle.vehicle_id,
            calibration_id=cal.calibration_id,
            seed=seed,
            sim_hz=request.sim_hz,
        )
        return view

    async def _monitor(self, rt: SessionRuntime) -> None:
        """``realtime_factor`` (1 Hz) e avisos ``realtime_degraded``/``telemetry_degraded``."""
        while not rt.closing:
            await asyncio.sleep(MONITOR_INTERVAL_S)
            try:
                stats = rt.handle.stats
            except Exception:
                return
            factor = rt.handle.real_time_factor * rt.steps_per_tick
            rt.update(realtime_factor=max(factor, 0.0))
            # O worker não mede o relógio (determinismo): recebe o fator para o canal
            # real_time_factor dos frames e do log (TickRecord.real_time_factor).
            with contextlib.suppress(Exception):
                await self.send(
                    rt, {"type": "telemetry.config", "real_time_factor": round(max(factor, 0.0), 4)}
                )
            rid = rt.view.active_run_id
            if rid is None:
                rt.low_rtf_samples = 0
                continue
            events = rt.run_events.setdefault(rid, set())
            rt.low_rtf_samples = rt.low_rtf_samples + 1 if factor < REALTIME_DEGRADED_FACTOR else 0
            if rt.low_rtf_samples >= REALTIME_DEGRADED_SAMPLES:
                events.add("realtime_degraded")
            if stats.telemetry_degraded:
                events.add("telemetry_degraded")

    # ------------------------------------------------------------------ comandos
    async def send(self, rt: SessionRuntime, command: dict[str, object]) -> None:
        if rt.worker_failed:
            raise SimRemapError(
                f"O worker da sessão {rt.session_id} não está disponível.",
                code="SIM_WORKER_UNAVAILABLE",
            )
        await rt.handle.send(command)

    async def request(
        self, rt: SessionRuntime, command: dict[str, object], timeout_s: float = ACK_TIMEOUT_S
    ) -> dict[str, Any]:
        """Envia ``command`` com ``request_id`` e espera o ``ack`` correspondente."""
        request_id = str(command.setdefault("request_id", uuid.uuid4().hex))
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        rt.acks[request_id] = future
        try:
            await self.send(rt, command)
            return await asyncio.wait_for(future, timeout_s)
        finally:
            rt.acks.pop(request_id, None)

    # ------------------------------------------------------------------ oficina
    async def install_upgrades(self, session_id: str, pkg: UpgradePackage) -> SimulationSession:
        """Instala ``pkg`` na sessão viva (o pacote substitui o anterior; ``stock`` desinstala)."""
        rt = await self._require_open(session_id)
        if rt.view.attempt_id is not None:
            raise dyno_error(
                "UPGRADES_LOCKED",
                "As peças de uma tentativa de cenário são fixas.",
                session_id=session_id,
            )
        if rt.view.active_run_id is not None:
            raise dyno_error(
                "RUN_IN_PROGRESS",
                f"A puxada {rt.view.active_run_id} está em andamento.",
                session_id=session_id,
            )
        if rt.worker_failed or rt.closing:
            raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
        upgraded = apply_upgrades(self.vehicles.vehicle_for_session(rt.view.vehicle_id), pkg)
        StructuralLimits.from_vehicle(upgraded.vehicle)
        try:
            ack = await self.request(
                rt,
                {
                    "type": "hardware.install",
                    "vehicle": upgraded.vehicle.model_dump(mode="json"),
                    "exhaust_backpressure_scale": upgraded.physics.exhaust_backpressure_scale,
                    "fuel_pump_capacity_scale": upgraded.physics.fuel_pump_capacity_scale,
                },
                INSTALL_TIMEOUT_S,
            )
        except TimeoutError:
            raise SimRemapError(
                "O worker não confirmou a instalação das peças.", code="SIM_WORKER_UNAVAILABLE"
            ) from None
        if not ack.get("ok"):
            code = str(ack.get("code") or "SIM_WORKER_UNAVAILABLE")
            raise SimRemapError(
                f"O worker recusou a instalação das peças ({code}).",
                code=code if is_registered(code) else "SIM_WORKER_UNAVAILABLE",
            )
        rt.vehicle = upgraded.vehicle
        weights = ack.get("rod_weights")
        if isinstance(weights, list):
            rt.rod_weights = [float(w) for w in weights]
        rt.update(upgrades=pkg, engine_locked=False, state="ready")
        await self.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        log.info(
            "session.upgrades_installed",
            session_id=session_id,
            vehicle_id=rt.view.vehicle_id,
            upgrades=pkg.non_stock(),
            exhaust_backpressure_scale=upgraded.physics.exhaust_backpressure_scale,
            fuel_pump_capacity_scale=upgraded.physics.fuel_pump_capacity_scale,
        )
        return rt.view

    # ------------------------------------------------------------------ puxadas
    async def _require_open(self, session_id: str) -> SessionRuntime:
        """Runtime da sessão; encerrada (só no banco) ⇒ 409 ``SESSION_CLOSED`` (E-09)."""
        rt = self._sessions.get(session_id)
        if rt is not None:
            return rt
        stored = await self.repo.get_session(session_id)
        if stored is not None and stored.state == "closed":
            raise dyno_error(
                "SESSION_CLOSED", f"A sessão {session_id} está encerrada.", session_id=session_id
            )
        return self.require(session_id)

    async def start_run(self, session_id: str, request: DynoRunRequest) -> DynoRun:
        rt = await self._require_open(session_id)
        limits = rt.vehicle.mechanical_limits
        guard = self.profile_guard
        pending = list(guard.can_start_run(session_id)) if guard is not None else []
        check_run_allowed(
            RunGuardInput(
                session_id=session_id,
                closed=rt.view.state == "closed" or rt.closing,
                engine_locked=rt.view.engine_locked,
                active_run_id=rt.view.active_run_id,
                attempt_id=rt.view.attempt_id,
                n_gears=len(rt.vehicle.gear_ratios),
                rev_limit_rpm=float(limits.rev_limit_rpm),
            ),
            request,
            pending_setup=pending,
        )
        if rt.worker_failed:
            raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
        run_id = new_run_id()
        run = DynoRun(
            run_id=run_id,
            session_id=session_id,
            run_type=request.run_type,
            request=request,
            state=RunState.ARMING,
            started_at_tick=round(rt.view.t_sim_s * rt.view.sim_hz),
            calibration_id=rt.calibration.calibration_id,
            calibration_hash=rt.calibration.content_hash,
            seed=rt.view.seed,
            sim_hz=rt.view.sim_hz,
        )
        if not await self.repo.save_run(run) and self.repo.available:
            raise SimRemapError(
                "Banco de dados indisponível ao registar a puxada.",
                code="DATABASE_UNAVAILABLE",
                headers={"Retry-After": "2"},
            )
        rt.runs[run_id] = run
        rt.run_done[run_id] = asyncio.get_running_loop().create_future()
        rt.update(active_run_id=run_id, state="running")
        try:
            await self.send(
                rt,
                {
                    "type": "run.start",
                    "run_id": run_id,
                    "request": request.model_dump(mode="json"),
                    "calibration_id": rt.calibration.calibration_id,
                },
            )
        except BaseException:
            rt.update(active_run_id=None, state="ready")
            rt.run_done.pop(run_id, None)
            raise
        log.info(
            "dyno.run_started", session_id=session_id, run_id=run_id, run_type=request.run_type
        )
        return run

    async def wait_run(
        self, session_id: str, run_id: str, timeout_s: float | None = None
    ) -> DynoRun:
        """Espera o ``run.result`` da puxada (``None`` = sem limite)."""
        rt = self.require(session_id)
        future = rt.run_done.get(run_id)
        if future is None:
            run = rt.runs.get(run_id) or await self.find_run(run_id)
            if run is None:
                raise dyno_error("RUN_NOT_FOUND", f"A puxada {run_id} não existe.")
            return run
        return await asyncio.wait_for(asyncio.shield(future), timeout_s)

    async def abort_run(
        self, session_id: str, run_id: str, reason: AbortReason = AbortReason.USER_ABORT
    ) -> DynoRun:
        rt = self.require(session_id)
        run = rt.runs.get(run_id)
        if run is None:
            stored = await self.find_run(run_id)
            if stored is None or stored.session_id != session_id:
                raise dyno_error("RUN_NOT_FOUND", f"A puxada {run_id} não existe.", run_id=run_id)
            run = stored
        if run.state in TERMINAL_RUN_STATES or rt.view.active_run_id != run_id:
            raise dyno_error(
                "RUN_NOT_ACTIVE",
                f"A puxada {run_id} já terminou ({run.state.value}).",
                state=run.state.value,
            )
        await self.send(rt, {"type": "run.abort", "run_id": run_id, "reason": reason.value})
        try:
            return await self.wait_run(session_id, run_id, RUN_RESULT_TIMEOUT_S)
        except TimeoutError:
            log.warning("dyno.abort_timeout", session_id=session_id, run_id=run_id)
            aborted = run.model_copy(update={"state": RunState.ABORTED, "abort_reason": reason})
            rt.runs[run_id] = aborted
            rt.update(active_run_id=None)
            with contextlib.suppress(Exception):
                await self.repo.save_run(aborted)
            return aborted

    async def find_run(self, run_id: str) -> DynoRun | None:
        for rt in self._sessions.values():
            run = rt.runs.get(run_id)
            if run is not None:
                return run
        return await self.repo.get_run(run_id)

    async def get_run(
        self,
        run_id: str,
        *,
        include_curve: bool = True,
        curve: Literal["raw", "smoothed"] = "smoothed",
    ) -> DynoRun:
        run = await self.find_run(run_id)
        if run is None:
            raise dyno_error("RUN_NOT_FOUND", f"A puxada {run_id} não existe.", run_id=run_id)
        if not include_curve:
            pulls = [p.model_copy(update={"curve": []}) for p in run.pulls]
            return run.model_copy(update={"curve": [], "pulls": pulls})
        if curve == "smoothed" and run.curve:
            window = run.request.smoothing_window
            pulls = [
                p.model_copy(update={"curve": smooth_curve(p.curve, window)}) for p in run.pulls
            ]
            return run.model_copy(update={"curve": smooth_curve(run.curve, window), "pulls": pulls})
        return run

    # ------------------------------------------------------------------ encerramento
    async def delete_session(self, session_id: str) -> None:
        rt = self._sessions.get(session_id)
        if rt is None or rt.view.state == "closed":
            raise dyno_error(
                "SESSION_NOT_FOUND", f"A sessão {session_id} não existe.", session_id=session_id
            )
        await self._close(rt, AbortReason.SESSION_CLOSED)

    async def _close(self, rt: SessionRuntime, reason: AbortReason) -> None:
        """Fecha a sessão uma só vez; chamadas concorrentes esperam o mesmo fecho.

        O abandono de uma tentativa e a baseline em fundo podem fechar a mesma sessão ao
        mesmo tempo. Os erros do fecho chegam a todos os que esperam (nada é engolido).
        """
        if rt.close_task is None:
            rt.close_task = asyncio.create_task(
                self._close_once(rt, reason), name=f"dyno-close-{rt.session_id}"
            )
        await asyncio.shield(rt.close_task)

    async def _close_once(self, rt: SessionRuntime, reason: AbortReason) -> None:
        rt.closing = True
        rid = rt.view.active_run_id
        if rid is not None and not rt.worker_failed:
            with contextlib.suppress(SimRemapError, TimeoutError):
                await self.send(rt, {"type": "run.abort", "run_id": rid, "reason": reason.value})
                await self.wait_run(rt.session_id, rid, CLOSE_TIMEOUT_S)
        await self.host.stop_session(rt.session_id)
        for task in (rt.router_task, rt.monitor_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        rid = rt.view.active_run_id
        if rid is not None:  # o worker não confirmou: fecha a puxada em memória
            run = rt.runs.get(rid)
            if run is not None and run.state not in TERMINAL_RUN_STATES:
                closed = run.model_copy(update={"state": RunState.ABORTED, "abort_reason": reason})
                rt.runs[rid] = closed
                await self.repo.save_run(closed)
        rt.update(state="closed", active_run_id=None)
        await self.repo.save_session(
            rt.view, data_version=rt.data_version, catalog_sha256=rt.catalog_sha256
        )
        self.streams.close(rt.session_id)
        if self._sessions.get(rt.session_id) is rt:
            del self._sessions[rt.session_id]
        log.info("dyno.session_closed", session_id=rt.session_id, reason=reason.value)

    async def shutdown(self) -> None:
        """Fecha todas as sessões (EC-11: puxada ativa ``aborted`` com ``session_closed``)."""
        for rt in list(self._sessions.values()):
            with contextlib.suppress(Exception):
                await self._close(rt, AbortReason.SESSION_CLOSED)
