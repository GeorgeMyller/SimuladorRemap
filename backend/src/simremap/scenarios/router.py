"""Endpoints do training-scenarios (rest-api 3.8: E-30 a E-45; D-REST-07, D-16).

Equivalência com o actions.md: T438 (``api/routers/profiles.py``), T439
(``api/routers/scenarios.py``), T440 (``api/routers/attempts.py``) e T441
(``api/routers/packages.py``) ficam neste módulo, ponto de registo fixo do componente em
``simremap.api.registry.COMPONENT_ROUTER_MODULES`` (layout ``<pacote>/router.py``).

- Feature flag ``SIMREMAP_FEATURE_SCENARIOS`` (D-27): desligada, todas as rotas devolvem
  404 ``ROUTE_NOT_FOUND``.
- O lifespan do router (depois dos do dyno-bench, ecu-core e telemetria) monta os
  serviços em ``app.state.scenarios`` (``ScenarioServices``), embrulha as portas de sessão
  para a ``CalibrationAudit``, carrega os cenários base (RF-04) e recupera avaliações
  interrompidas (EC-15).
- Cabeçalho ``X-Player-Profile-Id``: obrigatório nas tentativas, na criação de cenários
  e nos pacotes (400 ``PLAYER_PROFILE_REQUIRED``/404 ``PLAYER_PROFILE_NOT_FOUND``);
  opcional em E-32/E-34.
- Substituições para testes (lidas no lifespan se já existirem em ``app.state``):
  ``scenarios_sim_port``, ``scenarios_calibration_port`` e ``scenarios_vehicle_lookup``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from simremap import __version__
from simremap.api.deps import body_limit
from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.scenarios import errors as _errors  # noqa: F401 - regista os códigos
from simremap.scenarios.attempts import AttemptService
from simremap.scenarios.catalog import ScenarioCatalog, catalog_vehicle
from simremap.scenarios.contracts import (
    AttemptPage,
    AttemptView,
    Evaluation,
    HintReveal,
    PackageExportRequest,
    PackageImportResult,
    PlayerProfile,
    PlayerProfileCreate,
    ReplayAccepted,
    Role,
    ScenarioCreate,
    ScenarioStats,
    ScenarioSummary,
    ScenarioView,
    SignedPackage,
    SubmitAccepted,
    SubmitRequest,
)
from simremap.scenarios.errors import scenario_error
from simremap.scenarios.events import EventLog
from simremap.scenarios.packages import PACKAGE_MAX_BYTES, PackageService
from simremap.scenarios.ports import (
    AppSimulationPort,
    CalibrationAudit,
    CalibrationPort,
    EcuCalibrationPort,
    SimulationPort,
    install_audit,
    uninstall_audit,
)
from simremap.scenarios.profiles import PROFILE_HEADER, ProfileService, require_instructor
from simremap.scenarios.replay import ReplayService
from simremap.scenarios.repository import ScenarioRepository

__all__ = ["TAG", "ScenarioServices", "install_scenarios", "router"]

TAG: Final = "training-scenarios"
log = get_logger("simremap.scenarios")


# --------------------------------------------------------------------------- serviços


@dataclass(slots=True)
class ScenarioServices:
    repo: ScenarioRepository
    profiles: ProfileService
    catalog: ScenarioCatalog
    attempts: AttemptService
    packages: PackageService
    replay: ReplayService
    events: EventLog
    audit: CalibrationAudit
    sim: SimulationPort
    calibrations: CalibrationPort


def _flag(state: Any, name: str) -> bool:
    """Feature flag lida a cada uso de ``app.state.settings`` (padrão ligado)."""
    settings = getattr(state, "settings", None)
    return settings is None or bool(getattr(settings, name, True))


def install_scenarios(app: FastAPI) -> ScenarioServices:
    """Monta os serviços (idempotente) em ``app.state.scenarios``."""
    state = app.state
    existing: ScenarioServices | None = getattr(state, "scenarios", None)
    if existing is not None:
        return existing
    settings = getattr(state, "settings", None)
    maker = getattr(state, "sessionmaker", None)
    repo = ScenarioRepository(maker)
    sim: SimulationPort = getattr(state, "scenarios_sim_port", None) or AppSimulationPort(state)
    calibrations: CalibrationPort = getattr(
        state, "scenarios_calibration_port", None
    ) or EcuCalibrationPort(maker)
    vehicles = getattr(state, "scenarios_vehicle_lookup", None) or catalog_vehicle
    audit = CalibrationAudit()
    install_audit(state, audit)
    catalog = ScenarioCatalog(
        repo,
        calibrations,
        vehicles=vehicles,
        wastegate_enabled=lambda: _flag(state, "feature_defect_wastegate"),
        profile_enabled=(lambda p: True) if settings is None else settings.ecu_profile_enabled,
    )
    events = EventLog(repo)
    app_version = __version__ if settings is None else str(settings.app_version)
    services = ScenarioServices(
        repo=repo,
        profiles=ProfileService(repo),
        catalog=catalog,
        attempts=AttemptService(repo, catalog, sim, calibrations, events, audit),
        packages=PackageService(
            repo,
            catalog,
            sim,
            calibrations,
            events,
            app_version=app_version,
            install_id=lambda: getattr(state, "install_id", None),
        ),
        replay=ReplayService(repo, catalog, sim, calibrations, app_version=app_version),
        events=events,
        audit=audit,
        sim=sim,
        calibrations=calibrations,
    )
    state.scenarios = services
    return services


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getattr(app.state, "sessionmaker", None) is None:
        log.warning("scenarios.install_skipped", reason="sessionmaker ausente")
        yield
        return
    services = install_scenarios(app)
    try:
        outcome = await services.catalog.load_builtin()
        recovered = await services.attempts.recover()
        log.info("startup.scenarios", builtin=outcome, **recovered)
    except SimRemapError as exc:
        log.error("startup.scenarios_failed", code=exc.error_code)
    try:
        yield
    finally:
        await services.attempts.shutdown()
        await services.replay.shutdown()
        uninstall_audit(app.state)
        if hasattr(app.state, "scenarios"):
            delattr(app.state, "scenarios")
        log.info("shutdown.scenarios")


# --------------------------------------------------------------------------- rota


class ScenarioRoute(APIRoute):
    """Converte o 422 de schema de ``POST /scenarios`` em ``SCENARIO_INVALID`` (seção 9)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        converts = self.path.endswith("/scenarios") and "POST" in (self.methods or set())

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                if not converts:
                    raise
                err = exc.errors()[0] if exc.errors() else {}
                loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
                raise scenario_error(
                    "SCENARIO_INVALID", f"{loc}: {err.get('msg', 'inválido')}"[:2000], field=loc
                ) from exc

        return handler


def _feature_enabled(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and not settings.feature_scenarios:
        raise SimRemapError("A rota pedida não existe.", code="ROUTE_NOT_FOUND")


router = APIRouter(
    prefix="/api/v1",
    tags=[TAG],
    route_class=ScenarioRoute,
    lifespan=_lifespan,
    dependencies=[Depends(_feature_enabled)],
)


def services_of(request: Request) -> ScenarioServices:
    services: ScenarioServices | None = getattr(request.app.state, "scenarios", None)
    if services is None:
        raise SimRemapError(
            "Banco de dados indisponível.",
            code="DATABASE_UNAVAILABLE",
            headers={"Retry-After": "2"},
        )
    return services


Services = Annotated[ScenarioServices, Depends(services_of)]
ProfileHeader = Annotated[str | None, Header(alias=PROFILE_HEADER)]
ScenarioIdPath = Annotated[str, Path(pattern=r"^[0-9a-z][-0-9a-z]{2,63}$")]
AttemptIdPath = Annotated[str, Path(min_length=1, max_length=36)]


async def required_profile(
    request: Request, x_player_profile_id: ProfileHeader = None
) -> PlayerProfile:
    profile = await services_of(request).profiles.resolve(x_player_profile_id, required=True)
    assert profile is not None  # noqa: S101 - required=True nunca devolve None
    return profile


async def optional_profile(
    request: Request, x_player_profile_id: ProfileHeader = None
) -> PlayerProfile | None:
    return await services_of(request).profiles.resolve(x_player_profile_id, required=False)


Profile = Annotated[PlayerProfile, Depends(required_profile)]
OptionalProfile = Annotated[PlayerProfile | None, Depends(optional_profile)]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


_PROFILE_CODES: Final = ("PLAYER_PROFILE_REQUIRED", "PLAYER_PROFILE_NOT_FOUND")


# --------------------------------------------------------------------------- perfis


@router.get("/profiles", summary="Perfis de jogador da estação (E-30)")
async def list_profiles(services: Services) -> list[PlayerProfile]:
    return await services.profiles.list()


@router.post(
    "/profiles",
    status_code=201,
    summary="Cria um perfil local (E-31)",
    openapi_extra=_codes("NICKNAME_TAKEN", "PROFILE_LIMIT_REACHED", "VALIDATION_FAILED"),
)
async def create_profile(body: PlayerProfileCreate, services: Services) -> PlayerProfile:
    return await services.profiles.create(body)


# --------------------------------------------------------------------------- cenários


def _view_response(scenario: Any, profile: PlayerProfile | None, status: int = 200) -> Response:
    """``ScenarioView`` sem nova validação (o defeito redigido violaria ``defect_diagnosis``)."""
    return JSONResponse(_view(scenario, profile).model_dump(mode="json"), status_code=status)


def _view(scenario: Any, profile: PlayerProfile | None) -> ScenarioView:
    view = ScenarioView.model_validate(
        {**scenario.model_dump(), "has_hidden_defect": scenario.hidden_defect is not None}
    )
    if profile is not None and profile.role == Role.INSTRUCTOR:
        return view
    return view.model_copy(update={"hidden_defect": None})  # sigilo pedagógico (RF-03)


@router.get(
    "/scenarios",
    summary="Lista os cenários (E-32)",
    openapi_extra=_codes("VALIDATION_FAILED", "PLAYER_PROFILE_NOT_FOUND"),
)
async def list_scenarios(
    services: Services,
    profile: OptionalProfile,
    kind: Annotated[Literal["base", "challenge"] | None, Query()] = None,
) -> list[ScenarioSummary]:
    return await services.catalog.summaries(kind, profile)


@router.post(
    "/scenarios",
    status_code=201,
    response_model=ScenarioView,
    summary="Cria um desafio do instrutor (E-33)",
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "INSTRUCTOR_ROLE_REQUIRED",
        "VEHICLE_NOT_FOUND",
        "CALIBRATION_NOT_FOUND",
        "SCENARIO_ALREADY_EXISTS",
        "SCENARIO_INVALID",
        "VALIDATION_FAILED",
    ),
)
async def create_scenario(body: ScenarioCreate, services: Services, profile: Profile) -> Response:
    require_instructor(profile, "criar desafios")
    scenario = await services.catalog.create(body, profile)
    response = _view_response(scenario, profile, 201)
    response.headers["Location"] = f"/api/v1/scenarios/{scenario.scenario_id}"
    return response


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioView,
    summary="Cenário com briefing e critérios (E-34)",
    openapi_extra=_codes("SCENARIO_NOT_FOUND", "PLAYER_PROFILE_NOT_FOUND"),
)
async def get_scenario(
    scenario_id: ScenarioIdPath, services: Services, profile: OptionalProfile
) -> Response:
    return _view_response(await services.catalog.get(scenario_id), profile)


@router.get(
    "/scenarios/{scenario_id}/stats",
    summary="Taxa de conclusão do cenário (E-35)",
    openapi_extra=_codes("SCENARIO_NOT_FOUND", "VALIDATION_FAILED"),
)
async def scenario_stats(
    scenario_id: ScenarioIdPath,
    services: Services,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> ScenarioStats:
    await services.catalog.get(scenario_id)
    return await services.events.stats(scenario_id, from_, to)


@router.post(
    "/scenarios/{scenario_id}/attempts",
    status_code=201,
    summary="Inicia uma tentativa com puxada base automática (E-36)",
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "SCENARIO_NOT_FOUND",
        "SIM_CAPACITY_EXCEEDED",
        "SCENARIO_CALIBRATION_HASH_MISMATCH",
        "SIM_WORKER_UNAVAILABLE",
        "CALIBRATION_SERVICE_UNAVAILABLE",
    ),
)
async def start_attempt(
    scenario_id: ScenarioIdPath, services: Services, profile: Profile, response: Response
) -> AttemptView:
    attempt = await services.attempts.start(scenario_id, profile)
    response.headers["Location"] = f"/api/v1/attempts/{attempt.attempt_id}"
    return attempt


# --------------------------------------------------------------------------- tentativas


@router.get(
    "/attempts",
    summary="Tentativas com a última avaliação, por cursor (E-37)",
    openapi_extra=_codes(*_PROFILE_CODES, "VALIDATION_FAILED"),
)
async def list_attempts(  # noqa: PLR0917 - filtros de query
    services: Services,
    profile: Profile,
    scenario_id: Annotated[str | None, Query(max_length=64)] = None,
    origin: Annotated[Literal["local", "imported"] | None, Query()] = None,
    profile_id: Annotated[str | None, Query(max_length=36)] = None,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AttemptPage:
    rows, nxt = await services.repo.list_attempts(
        scenario_id=scenario_id, origin=origin, profile_id=profile_id, cursor=cursor, limit=limit
    )
    return AttemptPage(items=await services.attempts.views(rows), next_cursor=nxt)


@router.get(
    "/attempts/{attempt_id}",
    summary="Tentativa com puxadas classificadas e progresso (E-38)",
    openapi_extra=_codes(*_PROFILE_CODES, "ATTEMPT_NOT_FOUND"),
)
async def get_attempt(
    attempt_id: AttemptIdPath, services: Services, profile: Profile
) -> AttemptView:
    return await services.attempts.view(attempt_id)


@router.post(
    "/attempts/{attempt_id}/hints",
    summary="Revela a próxima dica (E-39)",
    openapi_extra=_codes(
        *_PROFILE_CODES, "ATTEMPT_NOT_OWNED", "ATTEMPT_NOT_FOUND", "HINT_LOCKED", "HINTS_EXHAUSTED"
    ),
)
async def reveal_hint(
    attempt_id: AttemptIdPath, services: Services, profile: Profile
) -> HintReveal:
    return await services.attempts.reveal_hint(attempt_id, profile)


@router.post(
    "/attempts/{attempt_id}/abandon",
    summary="Abandona a tentativa (E-40)",
    openapi_extra=_codes(
        *_PROFILE_CODES, "ATTEMPT_NOT_OWNED", "ATTEMPT_NOT_FOUND", "ATTEMPT_NOT_IN_PROGRESS"
    ),
)
async def abandon_attempt(
    attempt_id: AttemptIdPath, services: Services, profile: Profile
) -> AttemptView:
    return await services.attempts.abandon(attempt_id, profile)


@router.post(
    "/attempts/{attempt_id}/submit",
    status_code=202,
    summary="Submete a calibração para avaliação (E-41)",
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "ATTEMPT_NOT_OWNED",
        "ATTEMPT_NOT_FOUND",
        "ATTEMPT_NOT_IN_PROGRESS",
        "SUBMISSION_LIMIT_REACHED",
        "RUN_IN_PROGRESS",
        "CALIBRATION_NOT_IN_ATTEMPT",
    ),
)
async def submit_attempt(
    attempt_id: AttemptIdPath,
    body: SubmitRequest,
    services: Services,
    profile: Profile,
    response: Response,
) -> SubmitAccepted:
    accepted = await services.attempts.submit(attempt_id, profile, body)
    response.headers["Location"] = (
        f"/api/v1/attempts/{accepted.attempt_id}/evaluation?submission={accepted.submission_index}"
    )
    return accepted


@router.get(
    "/attempts/{attempt_id}/evaluation",
    summary="Avaliação da submissão (E-42)",
    openapi_extra=_codes(*_PROFILE_CODES, "ATTEMPT_NOT_FOUND", "EVALUATION_NOT_FOUND"),
)
async def get_evaluation(
    attempt_id: AttemptIdPath,
    services: Services,
    profile: Profile,
    submission: Annotated[int | None, Query(ge=1)] = None,
) -> Evaluation:
    return await services.attempts.evaluation(attempt_id, submission)


@router.post(
    "/attempts/{attempt_id}/replay",
    status_code=202,
    summary="Replay das puxadas de evidência de uma tentativa importada (E-43)",
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "INSTRUCTOR_ROLE_REQUIRED",
        "ATTEMPT_NOT_FOUND",
        "REPLAY_VERSION_INCOMPATIBLE",
        "SIM_CAPACITY_EXCEEDED",
    ),
)
async def replay_attempt(
    attempt_id: AttemptIdPath, services: Services, profile: Profile, response: Response
) -> ReplayAccepted:
    accepted = await services.replay.start(attempt_id, profile)
    response.headers["Location"] = f"/api/v1/attempts/{accepted.attempt_id}"
    return accepted


# --------------------------------------------------------------------------- pacotes


@router.post(
    "/packages/export",
    summary="Exporta um desafio ou uma tentativa como SignedPackage (E-44)",
    response_model=SignedPackage,
    openapi_extra=_codes(
        *_PROFILE_CODES,
        "SCENARIO_NOT_FOUND",
        "ATTEMPT_NOT_FOUND",
        "ATTEMPT_NOT_EVALUATED",
        "PACKAGE_NOT_CANONICALIZABLE",
        "PACKAGE_SERVICE_UNAVAILABLE",
    ),
)
async def export_package(
    body: PackageExportRequest, services: Services, profile: Profile
) -> Response:
    exported = await services.packages.export(body, profile)
    return JSONResponse(
        exported.package.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="{exported.filename}"'},
    )


@router.post(
    "/packages/import",
    status_code=201,
    summary="Importa um SignedPackage (E-45)",
    dependencies=[body_limit(PACKAGE_MAX_BYTES)],
    openapi_extra={
        **_codes(
            *_PROFILE_CODES,
            "INSTRUCTOR_ROLE_REQUIRED",
            "SCENARIO_NOT_FOUND",
            "SCENARIO_VERSION_MISMATCH",
            "PAYLOAD_TOO_LARGE",
            "PACKAGE_HASH_MISMATCH",
            "PACKAGE_FORMAT_UNSUPPORTED",
            "PACKAGE_MALFORMED",
            "PACKAGE_SCHEMA_INVALID",
            "PACKAGE_NOT_CANONICALIZABLE",
            "PACKAGE_SERVICE_UNAVAILABLE",
            "STORAGE_FULL",
        ),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/SignedPackage"}}
            },
        },
    },
)
async def import_package(
    request: Request, services: Services, profile: Profile, response: Response
) -> PackageImportResult:
    body = await request.body()
    result, created = await services.packages.import_package(body, profile)
    if not created:
        response.status_code = 200
    elif result.attempt_id is not None:
        response.headers["Location"] = f"/api/v1/attempts/{result.attempt_id}"
    else:
        response.headers["Location"] = f"/api/v1/scenarios/{result.scenario_id}"
    return result
