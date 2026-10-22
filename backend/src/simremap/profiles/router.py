"""Rotas REST do ecu-profiles (rest-api 3.6: E-21 a E-25; RF-01, RF-02, RF-13, RF-17 a RF-21).

Equivalência com o actions.md: T426 (``api/routers/ecu_profiles.py``) e T427
(``api/routers/session_ecu.py``) ficam neste módulo, ponto de registo fixo do componente
em ``simremap.api.registry.COMPONENT_ROUTER_MODULES``.

Estado da app (injetável):

- ``app.state.profiles_session_port``: ``ProfileSessionPort`` do dyno-bench (sem porta,
  E-23 a E-25 devolvem 404 ``SESSION_NOT_FOUND``);
- ``app.state.profiles_guard``: ``ProfileSessionGuard`` (criado no lifespan) consultado
  pelo dyno-bench antes de ``POST .../runs`` (409 ``ECU_SETUP_INCOMPLETE``);
- ``app.state.ecu_profile_hooks``: o lifespan instala ``RegistryHooksProvider`` (se não
  houver outro) para o ecu-core validar calibrações pela matriz de suporte (RF-04).

O lifespan constrói e valida o registo dos 4 perfis; descritor inválido impede o boot com
``PROFILE_REGISTRY_INVALID`` no log (RF-01). Erros de validação da ``BaseSetup`` voltam
como 422 ``BASE_SETUP_INVALID`` com ``field`` (caminho com pontos) e ``reason``; os do
assistente como 422 ``WIZARD_INPUT_INVALID``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final

from fastapi import APIRouter, FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from simremap.api.deps import SessionDep, SettingsDep
from simremap.catalog.service import get_catalog
from simremap.core.logging import get_logger
from simremap.ecu.contracts import EcuValidationError
from simremap.ecu.errors import from_validation
from simremap.ecu.repository import CalibrationRepository
from simremap.profiles.contracts import (
    BaseSetupResult,
    BaseSetupUpdate,
    EcuProfileDescriptor,
    EcuProfileSummary,
    FeaturePackage,
    SwapRequest,
    SwapResult,
)
from simremap.profiles.errors import profile_error
from simremap.profiles.registry import (
    ProfileRegistry,
    RegistryHooksProvider,
    RegistryInvalid,
    get_registry,
)
from simremap.profiles.repository import ProfileRepository
from simremap.profiles.service import ProfileService
from simremap.profiles.session_port import ProfileSessionPort
from simremap.profiles.setup import ProfileSessionGuard
from simremap.profiles.swap import SwapIdempotency

__all__ = ["TAG", "ProfilesRoute", "router"]

TAG: Final = "ecu-profiles"
logger = get_logger("simremap.profiles.router")

_SECTIONS: Final[dict[str, str]] = {
    "base_setup": "BASE_SETUP_INVALID",
    "wizard": "WIZARD_INPUT_INVALID",
}


def _validation_to_problem(exc: RequestValidationError) -> Exception:
    for err in exc.errors():
        original = (err.get("ctx") or {}).get("error")
        if isinstance(original, EcuValidationError):
            return from_validation(original)
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ())]
        if len(loc) >= 2 and loc[0] == "body" and loc[1] in _SECTIONS:  # noqa: PLR2004
            code = _SECTIONS[loc[1]]
            path = [p for p in loc[2:] if not p.startswith("function-")]
            field = ".".join(path) or loc[1]
            msg = str(err.get("msg", ""))
            reason = msg.removeprefix("Value error, ")
            return profile_error(
                code,
                f"Campo inválido: {field} ({reason})."[:2000],
                field=field,
                reason=reason,
            )
    return exc


class ProfilesRoute(APIRoute):
    """Converte erros de validação da base e do assistente nos códigos do perfil."""

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
    try:
        registry = get_registry()
    except RegistryInvalid as exc:
        logger.error(
            "startup.failed", code="PROFILE_REGISTRY_INVALID", reason=exc.code, detail=exc.detail
        )
        raise
    app.state.profiles_registry = registry
    if getattr(app.state, "profiles_guard", None) is None:
        app.state.profiles_guard = ProfileSessionGuard()
    if getattr(app.state, "profiles_idempotency", None) is None:
        app.state.profiles_idempotency = SwapIdempotency()
    if getattr(app.state, "ecu_profile_hooks", None) is None:
        app.state.ecu_profile_hooks = RegistryHooksProvider(registry)
    yield


router = APIRouter(prefix="/api/v1", tags=[TAG], route_class=ProfilesRoute, lifespan=_lifespan)

SessionIdPath = Annotated[str, Path(min_length=1, max_length=36)]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


def _registry(request: Request) -> ProfileRegistry:
    reg = getattr(request.app.state, "profiles_registry", None)
    return reg if isinstance(reg, ProfileRegistry) else get_registry()


def _service(request: Request, session: SessionDep, settings: SettingsDep) -> ProfileService:
    state = request.app.state
    port: ProfileSessionPort | None = getattr(state, "profiles_session_port", None)
    guard = getattr(state, "profiles_guard", None) or ProfileSessionGuard()
    idem = getattr(state, "profiles_idempotency", None) or SwapIdempotency()
    return ProfileService(
        port=port,
        repo=ProfileRepository(session),
        calibrations=CalibrationRepository(session),
        registry=_registry(request),
        catalog=get_catalog(),
        guard=guard,
        idempotency=idem,
        profile_enabled=settings.ecu_profile_enabled,
    )


# --------------------------------------------------------------------------- E-21


@router.get(
    "/ecu-profiles",
    response_model=list[EcuProfileSummary],
    summary="Lista os perfis de ECU (E-21)",
    openapi_extra=_codes("PROFILE_REGISTRY_INVALID"),
)
async def list_profiles(request: Request, settings: SettingsDep) -> list[EcuProfileSummary]:
    try:
        registry = _registry(request)
    except RegistryInvalid as exc:  # pragma: no cover - o boot já valida o registo
        raise profile_error("PROFILE_REGISTRY_INVALID", exc.detail) from exc
    return [s for s in registry.summaries() if settings.ecu_profile_enabled(s.profile_id.value)]


# --------------------------------------------------------------------------- E-22


@router.get(
    "/ecu-profiles/{profile_id}",
    response_model=EcuProfileDescriptor,
    summary="Descritor completo de um perfil de ECU (E-22)",
    openapi_extra=_codes("ECU_PROFILE_NOT_FOUND", "VEHICLE_NOT_FOUND", "PROFILE_REGISTRY_INVALID"),
)
async def get_profile(
    request: Request,
    settings: SettingsDep,
    profile_id: Annotated[str, Path(min_length=1, max_length=32)],
    vehicle_id: Annotated[str | None, Query(max_length=64)] = None,
    feature_package: Annotated[FeaturePackage | None, Query()] = None,
) -> EcuProfileDescriptor:
    registry = _registry(request)
    pid = registry.resolve(profile_id)
    if not settings.ecu_profile_enabled(pid.value):
        raise profile_error(
            "ECU_PROFILE_NOT_FOUND",
            f"O perfil de ECU {pid.value} não está ativo.",
            profile_id=pid.value,
        )
    vehicle = get_catalog().get_vehicle(vehicle_id) if vehicle_id is not None else None
    try:
        return registry.descriptor_for(pid, vehicle, feature_package)
    except RegistryInvalid as exc:
        raise profile_error("PROFILE_REGISTRY_INVALID", exc.detail) from exc


# --------------------------------------------------------------------------- E-23


@router.post(
    "/sessions/{session_id}/ecu/swap",
    response_model=SwapResult,
    summary="Troca a ECU da sessão (E-23)",
    openapi_extra=_codes(
        "SESSION_NOT_FOUND",
        "ECU_PROFILE_NOT_FOUND",
        "RUN_IN_PROGRESS",
        "SESSION_CLOSED",
        "SWAP_TARGET_INVALID",
        "SWAP_CONFIRMATION_REQUIRED",
        "SWAP_NOT_SUPPORTED_FOR_VEHICLE",
        "CALIBRATION_APPLY_TIMEOUT",
        "DATABASE_UNAVAILABLE",
    ),
)
async def swap_ecu(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    session_id: SessionIdPath,
    body: SwapRequest,
) -> SwapResult:
    service = _service(request, session, settings)
    result = await service.swap_ecu(session_id, body)
    logger.info(
        "profiles.swap",
        session_id=session_id,
        from_profile=result.previous_profile_id.value,
        to_profile=result.profile_id.value,
        ecu_state=result.ecu_state,
        snapshot_hash=result.oem_snapshot.content_hash if result.oem_snapshot else None,
    )
    return result


# --------------------------------------------------------------------------- E-24


@router.get(
    "/sessions/{session_id}/ecu/base-setup",
    response_model=BaseSetupResult,
    summary="Lê a configuração base, o checklist e a ficha de instalação (E-24)",
    openapi_extra=_codes("SESSION_NOT_FOUND"),
)
async def get_base_setup(
    request: Request, session: SessionDep, settings: SettingsDep, session_id: SessionIdPath
) -> BaseSetupResult:
    return await _service(request, session, settings).get_base_setup(session_id)


# --------------------------------------------------------------------------- E-25


@router.put(
    "/sessions/{session_id}/ecu/base-setup",
    response_model=BaseSetupResult,
    summary="Grava a configuração base e gera o mapa base (E-25)",
    openapi_extra=_codes(
        "SESSION_NOT_FOUND",
        "BASE_SETUP_NOT_EDITABLE_OEM",
        "BASE_SETUP_VERSION_CONFLICT",
        "RUN_IN_PROGRESS",
        "BASE_SETUP_INVALID",
        "WIZARD_INPUT_INVALID",
        "CALIBRATION_APPLY_TIMEOUT",
        "DATABASE_UNAVAILABLE",
    ),
)
async def put_base_setup(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    session_id: SessionIdPath,
    body: BaseSetupUpdate,
) -> BaseSetupResult:
    return await _service(request, session, settings).put_base_setup(session_id, body)
