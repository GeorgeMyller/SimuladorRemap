"""Portas dos cenários para os outros componentes (training-scenarios seção 10, NG-05).

O ``training-scenarios`` não calcula física, dano nem curvas: consome as APIs públicas dos
donos através destas portas (substituíveis nos testes):

- ``SimulationPort`` — sessões e puxadas do ``dyno-bench`` (``DynoService`` em
  ``app.state.dyno_service``), logs do ``telemetry-datalogger``
  (``app.state.telemetry_service``) e saúde do motor do ``knock-and-failure-model``
  (``app.state.damage_port``). Implementação: ``AppSimulationPort``.
- ``CalibrationPort`` — calibrações do ``ecu-core`` (``CalibrationRepository``):
  clonagem da calibração inicial, leitura de versões, criação por conteúdo embutido e
  cópia do payload de fábrica do catálogo (autocura dos builtin). Implementação:
  ``EcuCalibrationPort``.
- ``CalibrationAudit`` — regista as aplicações de calibração e as trocas de ECU de cada
  sessão (``t_sim_s`` e ``content_hash``) pelo ouvinte oficial do dyno-bench
  (``DynoService.add_calibration_listener``); a regra V-03 usa-o para detetar troca de
  calibração a meio de uma puxada.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.dyno.contracts import (
    TERMINAL_RUN_STATES,
    DynoRun,
    DynoRunRequest,
    SessionCreateRequest,
    SimulationSession,
)
from simremap.telemetry.datalog import LogData

__all__ = [
    "AppSimulationPort",
    "CalibrationApply",
    "CalibrationAudit",
    "CalibrationPort",
    "CalibrationRecord",
    "EcuCalibrationPort",
    "SimulationPort",
    "install_audit",
]

log = get_logger("simremap.scenarios")


# --------------------------------------------------------------------------- simulação


class SimulationPort(Protocol):
    """Operações do dyno-bench, da telemetria e do dano usadas pelas tentativas."""

    async def create_session(self, request: SessionCreateRequest) -> SimulationSession: ...
    async def delete_session(self, session_id: str) -> None: ...
    async def session(self, session_id: str) -> SimulationSession | None: ...
    async def start_run(self, session_id: str, request: DynoRunRequest) -> DynoRun: ...
    async def wait_run(self, session_id: str, run_id: str, timeout_s: float) -> DynoRun: ...
    async def runs_of(self, session_id: str) -> list[DynoRun]: ...
    async def get_run(self, run_id: str) -> DynoRun | None: ...
    async def load_log(self, run_id: str) -> LogData: ...
    async def restore_count(self, session_id: str) -> int | None: ...
    def current_calibration_hash(self, session_id: str) -> str | None: ...


class AppSimulationPort:
    """``SimulationPort`` sobre os serviços publicados em ``app.state``."""

    def __init__(self, state: Any) -> None:
        self._state = state

    def _dyno(self) -> Any:
        service = getattr(self._state, "dyno_service", None)
        if service is None:
            raise SimRemapError("Simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
        return service

    async def create_session(self, request: SessionCreateRequest) -> SimulationSession:
        session: SimulationSession = await self._dyno().create_session(request)
        return session

    async def delete_session(self, session_id: str) -> None:
        service = getattr(self._state, "dyno_service", None)
        if service is None or service.runtime(session_id) is None:
            return
        try:
            await service.delete_session(session_id)
        except SimRemapError as exc:
            if exc.error_code != "SESSION_NOT_FOUND":
                raise

    async def session(self, session_id: str) -> SimulationSession | None:
        service = getattr(self._state, "dyno_service", None)
        if service is None:
            return None
        try:
            view: SimulationSession = await service.get_session(session_id)
        except SimRemapError:
            return None
        return view

    async def start_run(self, session_id: str, request: DynoRunRequest) -> DynoRun:
        run: DynoRun = await self._dyno().start_run(session_id, request)
        return run

    async def wait_run(self, session_id: str, run_id: str, timeout_s: float) -> DynoRun:
        run: DynoRun = await self._dyno().wait_run(session_id, run_id, timeout_s)
        return run

    async def runs_of(self, session_id: str) -> list[DynoRun]:
        service = getattr(self._state, "dyno_service", None)
        if service is None:
            return []
        runs: dict[str, DynoRun] = {r.run_id: r for r in await service.repo.runs_of(session_id)}
        rt = service.runtime(session_id)
        if rt is not None:
            runs.update(rt.runs)
        return sorted(runs.values(), key=lambda r: (r.started_at_tick, r.run_id))

    async def get_run(self, run_id: str) -> DynoRun | None:
        service = getattr(self._state, "dyno_service", None)
        if service is None:
            return None
        run: DynoRun | None = await service.find_run(run_id)
        return run

    async def load_log(self, run_id: str) -> LogData:
        telemetry = getattr(self._state, "telemetry_service", None)
        if telemetry is None:
            raise SimRemapError("Datalogger indisponível.", code="LOG_NOT_FOUND")
        data: LogData = await telemetry.load_log(run_id, run=True)
        return data

    async def restore_count(self, session_id: str) -> int | None:
        port = getattr(self._state, "damage_port", None)
        if port is None:
            return None
        try:
            health = await port.live_health(session_id, False)
        except SimRemapError:
            return None
        return None if health is None else int(health.restore_count)

    def current_calibration_hash(self, session_id: str) -> str | None:
        service = getattr(self._state, "dyno_service", None)
        rt = None if service is None else service.runtime(session_id)
        return None if rt is None else str(rt.calibration.content_hash)


def run_is_terminal(run: DynoRun) -> bool:
    return run.state in TERMINAL_RUN_STATES


# --------------------------------------------------------------------------- calibração


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    """Versão de calibração do ecu-core vista pelos cenários."""

    calibration_id: str
    version: int
    vehicle_id: str
    profile_id: str
    content_hash: str
    content: dict[str, Any]  # CalibrationContent (vehicle_id, profile_id, fuel_model, ...)
    full: dict[str, Any]  # Calibration completa do GET (seção 3 de file-formats)


class CalibrationPort(Protocol):
    async def stock(self, vehicle_id: str, profile_id: str) -> CalibrationRecord | None: ...
    async def get(self, calibration_id: str, version: int | None = None) -> CalibrationRecord: ...
    async def create(self, content: dict[str, Any], name: str) -> CalibrationRecord: ...
    async def clone(self, source: CalibrationRecord, name: str) -> CalibrationRecord: ...
    async def factory_clone(
        self, vehicle_id: str, profile_id: str, name: str
    ) -> CalibrationRecord | None: ...
    def clone_hash(self, source: CalibrationRecord) -> str: ...


def _record(cal: Any) -> CalibrationRecord:
    from simremap.ecu.calibration import CONTENT_FIELDS

    full = cal.model_dump(mode="json")
    return CalibrationRecord(
        calibration_id=cal.calibration_id,
        version=cal.version,
        vehicle_id=cal.vehicle_id,
        profile_id=cal.profile_id.value,
        content_hash=cal.content_hash,
        content={k: full[k] for k in CONTENT_FIELDS},
        full=full,
    )


class EcuCalibrationPort:
    """``CalibrationPort`` sobre o ``CalibrationRepository`` do ecu-core."""

    def __init__(self, maker: async_sessionmaker[AsyncSession] | None) -> None:
        self._maker = maker

    def _require(self) -> async_sessionmaker[AsyncSession]:
        if self._maker is None:
            raise SimRemapError(
                "Serviço de calibração indisponível.", code="CALIBRATION_SERVICE_UNAVAILABLE"
            )
        return self._maker

    async def stock(self, vehicle_id: str, profile_id: str) -> CalibrationRecord | None:
        from simremap.ecu.repository import CalibrationRepository
        from simremap.ecu.service import stock_calibration_id

        cal_id = stock_calibration_id(vehicle_id, profile_id)
        async with self._require()() as db:
            repo = CalibrationRepository(db)
            if await repo.exists(cal_id):
                return _record(await repo.get(cal_id, 1))
        return None

    async def get(self, calibration_id: str, version: int | None = None) -> CalibrationRecord:
        from simremap.ecu.repository import CalibrationRepository

        async with self._require()() as db:
            return _record(await CalibrationRepository(db).get(calibration_id, version))

    async def create(self, content: dict[str, Any], name: str) -> CalibrationRecord:
        from simremap.ecu.calibration import CalibrationMetadata, parse_content
        from simremap.ecu.repository import CalibrationRepository

        parsed = parse_content(content)
        async with self._require()() as db:
            cal = await CalibrationRepository(db).create(
                parsed, CalibrationMetadata(name=name[:80], source="user")
            )
            await db.commit()
            return _record(cal)

    async def clone(self, source: CalibrationRecord, name: str) -> CalibrationRecord:
        return await self.create(source.content, name)

    async def factory_clone(
        self, vehicle_id: str, profile_id: str, name: str
    ) -> CalibrationRecord | None:
        """Calibração do usuário a partir do payload de fábrica do catálogo (sem ⇒ ``None``)."""
        from simremap.catalog.service import get_catalog

        try:
            payload = get_catalog().get_factory_calibration_payload(vehicle_id, profile_id)
        except SimRemapError:
            return None
        content = {**payload, "vehicle_id": vehicle_id, "profile_id": profile_id}
        try:
            return await self.create(content, name)
        except ValueError as exc:  # EcuValidationError e ValidationError do pydantic
            log.warning(
                "scenarios.factory_clone_invalid",
                vehicle_id=vehicle_id,
                profile_id=profile_id,
                reason=type(exc).__name__,
            )
            return None

    def clone_hash(self, source: CalibrationRecord) -> str:
        """``content_hash`` que ``clone(source)`` grava: o servidor recalcula após o
        ``parse_content`` (não é o ``content_hash`` guardado na versão de origem)."""
        from simremap.ecu.calibration import compute_content_hash, parse_content

        return compute_content_hash(parse_content(source.content))


# --------------------------------------------------------------------------- auditoria


@dataclass(frozen=True, slots=True)
class CalibrationApply:
    """Calibração aplicada numa sessão (ecu-core E-20 ou troca de ECU do ecu-profiles)."""

    t_sim_s: float
    calibration_id: str
    content_hash: str
    profile_id: str | None = None


class CalibrationAudit:
    """Histórico das aplicações de calibração por sessão (em memória, só sessões vivas)."""

    def __init__(self) -> None:
        self._items: dict[str, list[CalibrationApply]] = defaultdict(list)

    def record(self, session_id: str, item: CalibrationApply) -> None:
        self._items[session_id].append(item)

    def applies(self, session_id: str) -> list[CalibrationApply]:
        return list(self._items.get(session_id, ()))

    def hashes_between(self, session_id: str, t0: float, t1: float | None) -> set[str]:
        """``content_hash`` aplicados com ``t0 < t_sim_s ≤ t1`` (``t1 = None`` ⇒ sem fim)."""
        return {
            a.content_hash
            for a in self._items.get(session_id, ())
            if a.t_sim_s > t0 + 1e-9 and (t1 is None or a.t_sim_s <= t1 + 1e-9)
        }

    def calibration_ids(self, session_id: str) -> set[str]:
        return {a.calibration_id for a in self._items.get(session_id, ())}

    def forget(self, session_id: str) -> None:
        self._items.pop(session_id, None)


_AUDIT_REMOVER = "_scenarios_audit_remove"


def install_audit(state: Any, audit: CalibrationAudit) -> bool:
    """Liga a auditoria ao ouvinte oficial do dyno-bench (idempotente).

    ``DynoService.add_calibration_listener`` entrega cada ``calibration.apply`` e
    ``ecu.swap`` com ``ack`` ok (``applied_t_sim_s`` e ``content_hash``). Sem
    ``app.state.dyno_service`` não há auditoria (``False``).
    """
    if getattr(state, _AUDIT_REMOVER, None) is not None:
        return True
    service = getattr(state, "dyno_service", None)
    add = getattr(service, "add_calibration_listener", None)
    if not callable(add):
        log.warning("scenarios.audit_unavailable", reason="dyno_service ausente")
        return False

    def on_applied(event: Any) -> None:
        audit.record(
            str(event.session_id),
            CalibrationApply(
                t_sim_s=float(event.t_sim_s),
                calibration_id=str(event.calibration_id),
                content_hash=str(event.content_hash),
                profile_id=event.profile_id if event.kind == "ecu.swap" else None,
            ),
        )

    setattr(state, _AUDIT_REMOVER, add(on_applied))
    return True


def uninstall_audit(state: Any) -> None:
    remove = getattr(state, _AUDIT_REMOVER, None)
    if callable(remove):
        remove()
    if hasattr(state, _AUDIT_REMOVER):
        delattr(state, _AUDIT_REMOVER)


async def sleep(seconds: float) -> None:
    """``asyncio.sleep`` substituível nos testes (retries do traço)."""
    await asyncio.sleep(seconds)
