"""Endpoints do dyno-bench (rest-api 3.3: E-06 a E-11; dyno RF-01, RF-17, RF-22; D-REST-07).

O lifespan do router (fundido pelo FastAPI depois do lifespan da app, onde já existem
``sessionmaker`` e ``worker_host``) chama ``install_dyno(app)``, que publica em
``app.state``:

- ``dyno_service`` (``DynoService``) e ``dyno_stream_hub`` (``StreamHub``, ponto de
  assinatura do telemetry-datalogger);
- ``ecu_session_port`` (``DynoEcuSessionPort``), ``damage_port`` (``DynoDamagePort``) e
  ``profiles_session_port`` (``DynoProfileSessionPort``); a guarda de partida do
  ecu-profiles é lida de ``app.state.profiles_guard`` a cada ``POST .../runs``.

Substituições para testes (lidas em ``install_dyno`` se já existirem em ``app.state``):
``dyno_vehicle_source``, ``dyno_calibration_source`` e ``dyno_task_options`` (campos extra
do ``DynoInitPayload``, ex.: ``{"profile_hooks": "null", "steps_per_tick": 10}``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, FastAPI, Path, Query, Request, Response

from simremap.catalog.upgrades import UpgradePackage
from simremap.core.logging import get_logger
from simremap.dyno import errors as _errors  # noqa: F401 - regista os códigos do dyno
from simremap.dyno.contracts import DynoRun, DynoRunRequest, SessionCreateRequest, SimulationSession
from simremap.dyno.ports import DynoDamagePort, DynoEcuSessionPort, DynoProfileSessionPort
from simremap.dyno.repository import DynoRepository
from simremap.dyno.session import (
    CatalogVehicleSource,
    DynoService,
    RepositoryCalibrationSource,
)
from simremap.dyno.stream import StreamHub

__all__ = ["TAG", "get_service", "install_dyno", "router", "uninstall_dyno"]

TAG: Final = "dyno-bench"
log = get_logger("simremap.dyno")

SessionIdPath = Annotated[str, Path(min_length=1, max_length=36)]
RunIdPath = Annotated[str, Path(min_length=1, max_length=26)]


def install_dyno(app: FastAPI) -> DynoService:
    """Cria o ``DynoService`` e publica as portas em ``app.state`` (idempotente)."""
    state = app.state
    existing: DynoService | None = getattr(state, "dyno_service", None)
    if existing is not None:
        return existing
    settings = getattr(state, "settings", None)
    maker = getattr(state, "sessionmaker", None)
    vehicles = getattr(state, "dyno_vehicle_source", None) or CatalogVehicleSource()
    calibrations = getattr(state, "dyno_calibration_source", None) or RepositoryCalibrationSource(
        maker, vehicles
    )
    forensic = getattr(state, "forensic_service", None)
    if forensic is None:
        from simremap.damage.service import ForensicService  # noqa: PLC0415

        forensic = ForensicService(maker)
        state.forensic_service = forensic
    hub = StreamHub()
    service = DynoService(
        state.worker_host,
        repository=DynoRepository(maker),
        vehicles=vehicles,
        calibrations=calibrations,
        streams=hub,
        forensic=forensic,
        profile_guard=lambda: (
            getattr(state, "profiles_guard", None) or getattr(state, "profile_session_guard", None)
        ),
        profile_enabled=None if settings is None else settings.ecu_profile_enabled,
        enabled_strategies=(
            None
            if settings is None or settings.ecu_strategies_enabled is None
            else sorted(settings.ecu_strategies_enabled)
        ),
        task_options=getattr(state, "dyno_task_options", None),
        fps=50 if settings is None else settings.ws_fps,
    )
    state.dyno_service = service
    state.dyno_stream_hub = hub
    # Portas já instaladas (ex.: fakes de testes de outros componentes) não são trocadas.
    ports = {
        "ecu_session_port": DynoEcuSessionPort(service),
        "damage_port": DynoDamagePort(service),
        "profiles_session_port": DynoProfileSessionPort(service),
    }
    installed = []
    for name, port in ports.items():
        if getattr(state, name, None) is None:
            setattr(state, name, port)
            installed.append(name)
    state.dyno_installed_ports = installed
    return service


async def uninstall_dyno(app: FastAPI) -> None:
    """Fecha as sessões (EC-11) e retira as portas de ``app.state``."""
    service: DynoService | None = getattr(app.state, "dyno_service", None)
    if service is None:
        return
    await service.shutdown()
    names = ["dyno_service", "dyno_stream_hub", *getattr(app.state, "dyno_installed_ports", [])]
    for name in names:
        if hasattr(app.state, name):
            delattr(app.state, name)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getattr(app.state, "worker_host", None) is None:
        log.warning("dyno.install_skipped", reason="worker_host ausente")
        yield
        return
    service = install_dyno(app)
    closed = await service.repo.close_stale_sessions()
    log.info("startup.dyno", stale_sessions_closed=closed)
    try:
        yield
    finally:
        await uninstall_dyno(app)
        log.info("shutdown.dyno")


router = APIRouter(prefix="/api/v1", tags=[TAG], lifespan=_lifespan)


def get_service(request: Request) -> DynoService:
    service: DynoService | None = getattr(request.app.state, "dyno_service", None)
    if service is None:
        from simremap.core.errors import SimRemapError  # noqa: PLC0415

        raise SimRemapError("Simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
    return service


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


@router.post(
    "/sessions",
    status_code=201,
    summary="Cria uma sessão de simulação (E-06)",
    openapi_extra=_codes(
        "VEHICLE_NOT_FOUND",
        "CALIBRATION_NOT_FOUND",
        "ECU_PROFILE_NOT_FOUND",
        "SIM_CAPACITY_EXCEEDED",
        "VEHICLE_NOT_VALIDATED",
        "FUEL_NOT_ALLOWED",
        "VALIDATION_FAILED",
        "CALIBRATION_VEHICLE_MISMATCH",
        "SIM_WORKER_UNAVAILABLE",
        "PHYSICS_UNAVAILABLE",
        "DAMAGE_MODEL_UNAVAILABLE",
        "DATABASE_UNAVAILABLE",
    ),
)
async def create_session(
    body: SessionCreateRequest, request: Request, response: Response
) -> SimulationSession:
    session = await get_service(request).create_session(body)
    response.headers["Location"] = f"/api/v1/sessions/{session.session_id}"
    return session


@router.get(
    "/sessions/{session_id}",
    summary="Estado da sessão (E-07)",
    openapi_extra=_codes("SESSION_NOT_FOUND"),
)
async def get_session(session_id: SessionIdPath, request: Request) -> SimulationSession:
    return await get_service(request).get_session(session_id)


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Encerra a sessão (E-08)",
    openapi_extra=_codes("SESSION_NOT_FOUND"),
)
async def delete_session(session_id: SessionIdPath, request: Request) -> Response:
    await get_service(request).delete_session(session_id)
    return Response(status_code=204)


@router.put(
    "/sessions/{session_id}/upgrades",
    summary="Instala peças da oficina na sessão viva",
    openapi_extra=_codes(
        "SESSION_NOT_FOUND",
        "SESSION_CLOSED",
        "RUN_IN_PROGRESS",
        "UPGRADES_LOCKED",
        "UPGRADE_NOT_COMPATIBLE",
        "VALIDATION_FAILED",
        "SIM_WORKER_UNAVAILABLE",
    ),
)
async def install_upgrades(
    session_id: SessionIdPath, body: UpgradePackage, request: Request
) -> SimulationSession:
    return await get_service(request).install_upgrades(session_id, body)


@router.post(
    "/sessions/{session_id}/runs",
    status_code=202,
    summary="Inicia uma puxada (E-09)",
    openapi_extra=_codes(
        "SESSION_NOT_FOUND",
        "RUN_IN_PROGRESS",
        "ENGINE_DESTROYED",
        "SESSION_CLOSED",
        "ECU_SETUP_INCOMPLETE",
        "VALIDATION_FAILED",
        "RPM_RANGE_INVALID",
        "GEAR_NOT_AVAILABLE",
        "PROBE_NOT_ALLOWED",
        "SIM_WORKER_BUSY",
        "DATABASE_UNAVAILABLE",
    ),
)
async def start_run(
    session_id: SessionIdPath, body: DynoRunRequest, request: Request, response: Response
) -> DynoRun:
    run = await get_service(request).start_run(session_id, body)
    response.headers["Location"] = f"/api/v1/runs/{run.run_id}"
    return run


@router.post(
    "/sessions/{session_id}/runs/{run_id}/abort",
    summary="Aborta a puxada ativa (E-10)",
    openapi_extra=_codes("RUN_NOT_FOUND", "SESSION_NOT_FOUND", "RUN_NOT_ACTIVE"),
)
async def abort_run(session_id: SessionIdPath, run_id: RunIdPath, request: Request) -> DynoRun:
    return await get_service(request).abort_run(session_id, run_id)


@router.get(
    "/runs/{run_id}",
    summary="Puxada com resumo e curva (E-11)",
    openapi_extra=_codes("RUN_NOT_FOUND", "VALIDATION_FAILED"),
)
async def get_run(
    run_id: RunIdPath,
    request: Request,
    include_curve: Annotated[bool, Query()] = True,
    curve: Annotated[Literal["raw", "smoothed"], Query()] = "smoothed",
) -> DynoRun:
    return await get_service(request).get_run(run_id, include_curve=include_curve, curve=curve)
