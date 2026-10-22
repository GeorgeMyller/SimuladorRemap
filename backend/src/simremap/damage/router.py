"""Endpoints do knock-and-failure-model (rest-api 3.4: E-12 a E-14; RF-20, RF-21, RF-27).

As sessões e as puxadas pertencem ao ``dyno-bench``: o router lê-as pela porta
``app.state.damage_port`` (``DamageSessionPort``) e o serviço de laudos de
``app.state.forensic_service`` (criado sob demanda com o ``sessionmaker`` da app).
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Response

from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.damage.contracts import EngineHealth, EngineRestoreRequest, ForensicReport
from simremap.damage.service import ForensicService
from simremap.damage.session_port import DamageSessionPort, NullSessionPort, SessionView

__all__ = ["TAG", "get_damage_port", "get_forensic_service", "router"]

TAG: Final = "damage"
router = APIRouter(prefix="/api/v1", tags=[TAG])
log = get_logger("simremap.damage")

AudienceQuery = Literal["beginner", "intermediate", "instructor", "all"]
SessionIdPath = Annotated[str, Path(min_length=1, max_length=36)]
RunIdPath = Annotated[str, Path(min_length=1, max_length=26)]


def get_damage_port(request: Request) -> DamageSessionPort:
    port: DamageSessionPort | None = getattr(request.app.state, "damage_port", None)
    return port if port is not None else NullSessionPort()


def get_forensic_service(request: Request) -> ForensicService:
    service: ForensicService | None = getattr(request.app.state, "forensic_service", None)
    if service is None:
        service = ForensicService(getattr(request.app.state, "sessionmaker", None))
        request.app.state.forensic_service = service
    return service


PortDep = Annotated[DamageSessionPort, Depends(get_damage_port)]
ServiceDep = Annotated[ForensicService, Depends(get_forensic_service)]


def _errors(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


async def _session_or_404(port: DamageSessionPort, session_id: str) -> SessionView:
    view = await port.get_session(session_id)
    if view is None:
        raise SimRemapError(f"A sessão {session_id} não existe.", code="SESSION_NOT_FOUND")
    return view


@router.get(
    "/sessions/{session_id}/engine/health",
    summary="Saúde do motor da sessão (E-12)",
    openapi_extra=_errors("SESSION_NOT_FOUND", "SESSION_CLOSED", "SIM_WORKER_UNAVAILABLE"),
)
async def get_engine_health(
    session_id: SessionIdPath,
    port: PortDep,
    service: ServiceDep,
    include_failures: Annotated[bool, Query()] = True,
) -> EngineHealth:
    view = await _session_or_404(port, session_id)
    health = await port.live_health(session_id, include_failures)
    if health is None:
        health = await service.load_engine_health(view, include_failures)
    if health is None and view.closed:  # encerrada sem saúde gravada (nenhuma puxada)
        raise SimRemapError(f"A sessão {session_id} está encerrada.", code="SESSION_CLOSED")
    if health is None:
        raise SimRemapError("Worker de simulação indisponível.", code="SIM_WORKER_UNAVAILABLE")
    return health


@router.post(
    "/sessions/{session_id}/engine/restore",
    summary="Restaura o motor de série (E-13)",
    openapi_extra=_errors(
        "SESSION_NOT_FOUND", "RUN_IN_PROGRESS", "SESSION_CLOSED", "SIM_WORKER_UNAVAILABLE"
    ),
)
async def restore_engine(
    session_id: SessionIdPath,
    port: PortDep,
    service: ServiceDep,
    body: Annotated[EngineRestoreRequest | None, Body()] = None,
) -> EngineHealth:
    view = await _session_or_404(port, session_id)
    if view.closed:
        raise SimRemapError(f"A sessão {session_id} está encerrada.", code="SESSION_CLOSED")
    if view.active_run_id is not None:
        raise SimRemapError(
            f"A puxada {view.active_run_id} está em andamento.", code="RUN_IN_PROGRESS"
        )
    health = await port.restore_engine(session_id, None if body is None else body.note)
    await service.persist_engine_health(
        health, await port.rod_weights(session_id), tick=round(health.t_sim_s * 1000)
    )
    log.info("damage.restore", session_id=session_id, restore_count=health.restore_count)
    return health


@router.get(
    "/runs/{run_id}/forensic-report",
    summary="Laudo forense da puxada (E-14)",
    openapi_extra=_errors(
        "RUN_NOT_FOUND", "FORENSIC_REPORT_NOT_FOUND", "FORENSIC_REPORT_PENDING", "VALIDATION_FAILED"
    ),
)
async def get_forensic_report(
    run_id: RunIdPath,
    response: Response,
    port: PortDep,
    service: ServiceDep,
    audience: Annotated[AudienceQuery, Query()] = "all",
) -> ForensicReport:
    if await port.get_run(run_id) is None:
        raise SimRemapError(f"A puxada {run_id} não existe.", code="RUN_NOT_FOUND")
    report, persisted = await service.get_report(run_id)
    if not persisted:
        response.headers["X-Simremap-Persisted"] = "false"
    if audience != "all":
        report = report.model_copy(update={"texts": {audience: report.texts[audience]}})
    return report
