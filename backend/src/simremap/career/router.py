"""Endpoints do Modo Carreira em ``/api/v1/career`` (002 interfaces/career.md; D-15).

- ``GET /career/orders``: ordens de serviço fixas.
- ``GET /career/profiles/{profile_id}``: perfil da oficina (criado com R$ 5.000,00 e
  reputação 50 na primeira leitura); ``profile_id`` é o perfil local de jogador.
- ``POST /career/profiles/{profile_id}/jobs``: aceita uma ordem e cria a tentativa.
- ``POST /career/jobs/{job_id}/settle``: liquida o job (idempotente).
- ``GET /career/profiles/{profile_id}/jobs``: histórico.

Usa os serviços do training-scenarios (``app.state.scenarios``); sem eles ⇒ 503
``DATABASE_UNAVAILABLE``. Atrás da mesma feature flag ``SIMREMAP_FEATURE_SCENARIOS``.
Erros em ``application/problem+json``.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Request, Response

from simremap.career import errors as _errors  # noqa: F401 - regista os códigos
from simremap.career.contracts import CareerJob, CareerProfile, JobAccept, WorkOrder
from simremap.career.repository import CareerRepository
from simremap.career.service import CareerService
from simremap.core.errors import SimRemapError

__all__ = ["TAG", "career_of", "router"]

TAG: Final = "career"
_PROFILE_CODES: Final = ("PLAYER_PROFILE_NOT_FOUND",)


def _feature_enabled(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and not settings.feature_scenarios:
        raise SimRemapError("A rota pedida não existe.", code="ROUTE_NOT_FOUND")


router = APIRouter(prefix="/api/v1/career", tags=[TAG], dependencies=[Depends(_feature_enabled)])


def career_of(request: Request) -> CareerService:
    """``CareerService`` ligado aos serviços dos cenários da app (montado no 1.º uso)."""
    state = request.app.state
    scenarios = getattr(state, "scenarios", None)
    if scenarios is None:
        raise SimRemapError(
            "Banco de dados indisponível.",
            code="DATABASE_UNAVAILABLE",
            headers={"Retry-After": "2"},
        )
    service: CareerService | None = getattr(state, "career", None)
    if service is None or service.attempts is not scenarios.attempts:
        repo = CareerRepository(getattr(state, "sessionmaker", None))
        service = CareerService(repo, scenarios.attempts, scenarios.profiles)
        state.career = service
    return service


Career = Annotated[CareerService, Depends(career_of)]
ProfileIdPath = Annotated[str, Path(min_length=1, max_length=36)]
JobIdPath = Annotated[str, Path(min_length=1, max_length=36)]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


@router.get("/orders", summary="Ordens de serviço disponíveis")
async def list_orders(career: Career) -> list[WorkOrder]:
    return career.list_orders()


@router.get(
    "/profiles/{profile_id}",
    summary="Perfil da oficina (saldo e reputação)",
    openapi_extra=_codes(*_PROFILE_CODES),
)
async def get_profile(profile_id: ProfileIdPath, career: Career) -> CareerProfile:
    return await career.profile(profile_id)


@router.get(
    "/profiles/{profile_id}/jobs",
    summary="Histórico de serviços do perfil",
    openapi_extra=_codes(*_PROFILE_CODES),
)
async def list_jobs(profile_id: ProfileIdPath, career: Career) -> list[CareerJob]:
    return await career.jobs(profile_id)


@router.post(
    "/profiles/{profile_id}/jobs",
    status_code=201,
    summary="Aceita uma ordem e cria a tentativa do cenário",
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "CAREER_ORDER_NOT_FOUND",
        "CAREER_JOB_ALREADY_OPEN",
        "CAREER_REPUTATION_TOO_LOW",
        "SCENARIO_NOT_FOUND",
        "SIM_CAPACITY_EXCEEDED",
        "VALIDATION_FAILED",
    ),
)
async def accept_order(
    profile_id: ProfileIdPath, body: JobAccept, career: Career, response: Response
) -> CareerJob:
    job = await career.accept(profile_id, body.order_id)
    response.headers["Location"] = f"/api/v1/career/jobs/{job.job_id}"
    return job


@router.post(
    "/jobs/{job_id}/settle",
    summary="Liquida o serviço pela tentativa (idempotente)",
    openapi_extra=_codes("CAREER_JOB_NOT_FOUND", "CAREER_ATTEMPT_NOT_FINISHED"),
)
async def settle_job(job_id: JobIdPath, career: Career) -> CareerJob:
    return await career.settle(job_id)
