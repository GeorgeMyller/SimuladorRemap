"""Rotas REST do ecu-core (rest-api 3.5: E-15 a E-20; ecu-core RF-25 a RF-28; D-15, D-REST-03).

Equivalência com o actions.md: T419 (``api/routers/calibrations.py``) e T420
(``api/routers/session_calibration.py``) ficam neste módulo, ponto de registo fixo do
componente em ``simremap.api.registry.COMPONENT_ROUTER_MODULES``.

Estado da app consumido (injetável, ver ``ecu/ports.py`` e ``ecu/session_port.py``):
``app.state.ecu_session_port`` (dyno-bench), ``app.state.ecu_vehicle_lookup``
(vehicle-catalog), ``app.state.ecu_profile_hooks`` (ecu-profiles) e, só em testes,
``app.state.ecu_stock_sources``.

Erros de validação de tabela/estratégia levantados dentro dos modelos Pydantic voltam
com o ``code`` do domínio (ex.: 422 ``TABLE_AXIS_NOT_MONOTONIC``) e não como
``VALIDATION_FAILED``: a classe de rota ``EcuRoute`` extrai o ``EcuValidationError``
original do ``RequestValidationError``.

O lifespan do router materializa as calibrações de série (``seed_stock``) depois das
migrações do lifespan da app.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Body, FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from simremap.api.deps import SessionDep, SettingsDep
from simremap.core.logging import get_logger
from simremap.ecu.apply import apply_to_session
from simremap.ecu.calibration import (
    ApplyCalibrationRequest,
    ApplyCalibrationResult,
    CalibrationCreate,
    CalibrationPage,
    CalibrationReplace,
    CalibrationResponse,
    CalibrationRevert,
    TablePatch,
    TablePatchResult,
)
from simremap.ecu.contracts import EcuValidationError
from simremap.ecu.errors import ecu_error, from_validation
from simremap.ecu.hooks import ProfileHooks
from simremap.ecu.ports import NullHooksProvider, ProfileHooksProvider, VehicleLookup
from simremap.ecu.repository import CalibrationRepository
from simremap.ecu.seed_stock import discover_stock_sources, seed_stock_calibrations
from simremap.ecu.service import create_calibration, replace_calibration
from simremap.ecu.session_port import SessionRegistryPort
from simremap.ecu.tables import table_view

__all__ = ["TAG", "EcuRoute", "router"]

TAG: Final = "ecu-core"
logger = get_logger("simremap.ecu.router")

_STRATEGY_LOCS: Final = frozenset({"strategies"})
STOCK_PREFIX: Final = "stock-"


def _validation_to_problem(exc: RequestValidationError) -> Exception:
    for err in exc.errors():
        original = (err.get("ctx") or {}).get("error")
        if isinstance(original, EcuValidationError):
            return from_validation(original)
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        if _STRATEGY_LOCS.intersection(loc) and err.get("type") == "value_error":
            return ecu_error(
                "STRATEGY_CONFIG_INVALID",
                f"Configuração de estratégia inválida: {err.get('msg', '')}"[:2000],
                fields=[".".join(loc[1:])],
                reason=str(err.get("msg", "")),
            )
    return exc


class EcuRoute(APIRoute):
    """Converte ``EcuValidationError`` (direto ou dentro do Pydantic) em ``ProblemDetail``."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except RequestValidationError as exc:
                raise _validation_to_problem(exc) from exc
            except EcuValidationError as exc:
                raise from_validation(exc) from exc

        return handler


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    maker = getattr(app.state, "sessionmaker", None)
    if maker is not None:
        sources = getattr(app.state, "ecu_stock_sources", None)
        try:
            report = await seed_stock_calibrations(
                maker, sources if sources is not None else discover_stock_sources()
            )
            app.state.ecu_seed_report = report
        except Exception as exc:  # seed não bloqueia o arranque (o catálogo é o portão)
            logger.error("ecu.seed_stock.failed", reason=type(exc).__name__)
    yield


router = APIRouter(prefix="/api/v1", tags=[TAG], route_class=EcuRoute, lifespan=_lifespan)

CalibrationIdPath = Annotated[str, Path(pattern=r"^[0-9a-z][-_0-9a-z]{0,63}$")]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


def _ensure_editable(calibration_id: str) -> None:
    """``stock-*`` é só leitura (D-03): a recusa vem antes de qualquer escrita."""
    if calibration_id.startswith(STOCK_PREFIX):
        raise ecu_error("CALIBRATION_STOCK_IMMUTABLE", calibration_id=calibration_id)


def _hooks(request: Request, profile_id: str) -> ProfileHooks:
    provider: ProfileHooksProvider = (
        getattr(request.app.state, "ecu_profile_hooks", None) or NullHooksProvider()
    )
    return provider.hooks_for(profile_id)


# --------------------------------------------------------------------------- E-15


@router.get(
    "/calibrations",
    response_model=CalibrationPage,
    summary="Lista calibrações (E-15)",
    openapi_extra=_codes("VALIDATION_FAILED", "DATABASE_UNAVAILABLE"),
)
async def list_calibrations(
    session: SessionDep,
    vehicle_id: Annotated[str | None, Query(max_length=64)] = None,
    profile_id: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CalibrationPage:
    return await CalibrationRepository(session).list(vehicle_id, profile_id, limit, offset)


# --------------------------------------------------------------------------- E-16


@router.post(
    "/calibrations",
    status_code=201,
    response_model=CalibrationResponse,
    summary="Cria uma calibração (E-16)",
    openapi_extra=_codes(
        "VEHICLE_NOT_FOUND",
        "ECU_PROFILE_NOT_FOUND",
        "CALIBRATION_NOT_FOUND",
        "TABLE_AXIS_NOT_MONOTONIC",
        "TABLE_SIZE_EXCEEDED",
        "TABLE_VALUE_NOT_FINITE",
        "TABLE_VALUE_OUT_OF_RANGE",
        "TABLE_SHAPE_MISMATCH",
        "TABLE_UNIT_MISMATCH",
        "TABLE_ID_MISMATCH",
        "STRATEGY_KIND_MISMATCH",
        "STRATEGY_CONFIG_INVALID",
        "STRATEGY_NOT_SUPPORTED_BY_PROFILE",
        "VALIDATION_FAILED",
        "DATABASE_UNAVAILABLE",
    ),
)
async def post_calibration(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    body: CalibrationCreate,
) -> CalibrationResponse:
    profile = body.profile_id.value
    if not settings.ecu_profile_enabled(profile):
        raise ecu_error("ECU_PROFILE_NOT_FOUND", f"O perfil {profile} não está ativo.")
    lookup: VehicleLookup | None = getattr(request.app.state, "ecu_vehicle_lookup", None)
    if lookup is not None and not await lookup.vehicle_exists(body.vehicle_id):
        raise ecu_error(
            "VEHICLE_NOT_FOUND",
            f"O veículo {body.vehicle_id} não existe.",
            vehicle_id=body.vehicle_id,
        )
    repo = CalibrationRepository(session)
    cal = await create_calibration(repo, body, _hooks(request, profile))
    response.headers["Location"] = f"/api/v1/calibrations/{cal.calibration_id}"
    return CalibrationResponse.from_calibration(cal)


# --------------------------------------------------------------------------- E-17


@router.get(
    "/calibrations/{calibration_id}",
    response_model=CalibrationResponse,
    summary="Lê uma versão de calibração (E-17)",
    openapi_extra=_codes("CALIBRATION_NOT_FOUND", "CALIBRATION_VERSION_NOT_FOUND"),
)
async def get_calibration(
    session: SessionDep,
    calibration_id: CalibrationIdPath,
    version: Annotated[int | None, Query(ge=1)] = None,
    include: Annotated[Literal["versions"] | None, Query()] = None,
) -> CalibrationResponse:
    repo = CalibrationRepository(session)
    cal = await repo.get(calibration_id, version)
    versions = await repo.versions(calibration_id) if include == "versions" else None
    return CalibrationResponse.from_calibration(cal, versions)


# --------------------------------------------------------------------------- E-18


@router.put(
    "/calibrations/{calibration_id}",
    response_model=CalibrationResponse,
    summary="Substitui ou reverte a calibração, criando versão nova (E-18)",
    openapi_extra=_codes(
        "CALIBRATION_NOT_FOUND",
        "CALIBRATION_VERSION_NOT_FOUND",
        "CALIBRATION_VERSION_CONFLICT",
        "CALIBRATION_VERSION_LIMIT",
        "CALIBRATION_PROFILE_IMMUTABLE",
        "CALIBRATION_STOCK_IMMUTABLE",
        "STRATEGY_CONFIG_INVALID",
        "TABLE_VALUE_OUT_OF_RANGE",
        "DATABASE_UNAVAILABLE",
    ),
)
async def put_calibration(
    request: Request,
    session: SessionDep,
    calibration_id: CalibrationIdPath,
    body: Annotated[CalibrationRevert | CalibrationReplace, Body()],
) -> CalibrationResponse:
    _ensure_editable(calibration_id)
    repo = CalibrationRepository(session)
    if isinstance(body, CalibrationRevert):
        cal = await repo.revert(
            calibration_id,
            body.base_version,
            body.revert_to_version,
            change_summary=body.change_summary,
            author_nickname=body.author_nickname,
        )
    else:
        current = await repo.get(calibration_id)
        cal = await replace_calibration(
            repo, calibration_id, body, _hooks(request, current.profile_id.value)
        )
    return CalibrationResponse.from_calibration(cal)


# --------------------------------------------------------------------------- E-19


@router.patch(
    "/calibrations/{calibration_id}/tables/{table_id}",
    response_model=TablePatchResult,
    summary="Edita células e eixos de uma tabela, criando versão nova (E-19)",
    openapi_extra=_codes(
        "CALIBRATION_NOT_FOUND",
        "TABLE_NOT_FOUND",
        "CALIBRATION_STOCK_IMMUTABLE",
        "CALIBRATION_VERSION_CONFLICT",
        "CALIBRATION_VERSION_LIMIT",
        "TABLE_VALUE_OUT_OF_RANGE",
        "TABLE_VALUE_NOT_FINITE",
        "TABLE_AXIS_NOT_MONOTONIC",
        "PATCH_TOO_LARGE",
        "PATCH_CELL_OUT_OF_BOUNDS",
        "DATABASE_UNAVAILABLE",
    ),
)
async def patch_table(
    session: SessionDep,
    calibration_id: CalibrationIdPath,
    table_id: Annotated[str, Path(pattern=r"^[a-z][_0-9a-z]{1,47}$")],
    body: TablePatch,
) -> TablePatchResult:
    _ensure_editable(calibration_id)
    cal, table = await CalibrationRepository(session).patch_table(calibration_id, table_id, body)
    return TablePatchResult.model_validate(
        {"version": cal.version, "content_hash": cal.content_hash, "table": table_view(table)}
    )


# --------------------------------------------------------------------------- E-20


@router.post(
    "/sessions/{session_id}/calibration",
    response_model=ApplyCalibrationResult,
    summary="Aplica uma versão de calibração à sessão (E-20)",
    openapi_extra=_codes(
        "SESSION_NOT_FOUND",
        "CALIBRATION_NOT_FOUND",
        "CALIBRATION_VERSION_NOT_FOUND",
        "TABLE_NOT_LIVE_TUNABLE",
        "CALIBRATION_PROFILE_MISMATCH",
        "CALIBRATION_VEHICLE_MISMATCH",
        "SIM_WORKER_BUSY",
        "CALIBRATION_APPLY_TIMEOUT",
    ),
)
async def apply_session_calibration(
    request: Request,
    session: SessionDep,
    session_id: Annotated[str, Path(min_length=1, max_length=36)],
    body: ApplyCalibrationRequest,
) -> ApplyCalibrationResult:
    port: SessionRegistryPort | None = getattr(request.app.state, "ecu_session_port", None)
    info = await port.get_session(session_id) if port is not None else None
    hooks = _hooks(request, info.profile_id if info is not None else "ft-pro")
    return await apply_to_session(
        session_id=session_id,
        request=body,
        port=port,
        repo=CalibrationRepository(session),
        hooks=hooks,
    )
