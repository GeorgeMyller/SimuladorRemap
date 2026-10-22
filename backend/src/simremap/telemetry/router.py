"""Endpoints do telemetry-datalogger (rest-api 3.7: E-26 a E-29) e o WebSocket de telemetria
(websocket-telemetry; tel RF-01, RF-04, RF-17 a RF-19; D-REST-10; D-27; D-33).

- ``GET /api/v1/telemetry/channels?vehicle_id=`` → catálogo expandido por cilindro;
- ``GET /api/v1/runs/{run_id}/log?format=json|csv`` → ``DataLog`` (JSON) ou CSV em streaming,
  com ``X-Log-Sha256`` e ``Content-Disposition``;
- ``POST /api/v1/logs/import`` → 201 ``DataLogSummary`` (``log_id = "imp-" + 12 hex``);
- ``POST /api/v1/logs/compare`` → ``LogComparison``;
- ``WS /ws/v1/sessions/{session_id}/telemetry``.

O lifespan do router corre depois do do dyno-bench (ordem de ``COMPONENT_ROUTER_MODULES``)
e instala o ``TelemetryService`` em ``app.state.telemetry_service`` (amostrador do worker e
``TelemetryStream`` no hub do dyno). Flag ``SIMREMAP_FEATURE_TELEMETRY = false``: o serviço
não é instalado, as rotas REST devolvem 404 ``ROUTE_NOT_FOUND`` e o WebSocket fecha com 4404.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.routing import WebSocketRoute

from simremap.api.deps import body_limit
from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger
from simremap.telemetry import errors as _errors  # noqa: F401 - regista os códigos
from simremap.telemetry.channels import catalog_for_vehicle
from simremap.telemetry.compare import compare_logs, summary_of
from simremap.telemetry.contracts import (
    DataLogSummary,
    LogCompareRequest,
    LogComparison,
    LogRef,
    TelemetryChannel,
)
from simremap.telemetry.datalog import MAX_IMPORT_BYTES, LogData, parse_import
from simremap.telemetry.errors import telemetry_error
from simremap.telemetry.export import iter_csv, iter_json, select_channels
from simremap.telemetry.service import TelemetryService
from simremap.telemetry.ws import serve_telemetry

__all__ = ["TAG", "get_telemetry", "router"]

TAG: Final = "telemetry-datalogger"
log = get_logger("simremap.telemetry")

WS_PATH: Final = "/ws/v1/sessions/{session_id}/telemetry"
RunIdPath = Annotated[str, Path(min_length=1, max_length=36, pattern=r"^[0-9A-Za-z_-]+$")]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = getattr(app.state, "settings", None)
    if settings is not None and not settings.feature_telemetry:
        log.info("telemetry.disabled")
        yield
        return
    dyno = getattr(app.state, "dyno_service", None)
    maker = getattr(app.state, "sessionmaker", None)
    data_dir = settings.data_dir if settings is not None else None
    if data_dir is None:  # pragma: no cover - a app cria sempre Settings
        yield
        return
    service = TelemetryService(
        maker, data_dir, dyno, default_fps=50 if settings is None else settings.ws_fps
    )
    service.install()
    app.state.telemetry_service = service
    log.info("startup.telemetry", dyno=dyno is not None)
    try:
        yield
    finally:
        if dyno is not None:  # fecha as sessões antes do banco: os logs em curso são gravados
            await dyno.shutdown()
        await service.shutdown()
        if hasattr(app.state, "telemetry_service"):
            delattr(app.state, "telemetry_service")
        log.info("shutdown.telemetry")


router = APIRouter(tags=[TAG], lifespan=_lifespan)


def get_telemetry(request: Request) -> TelemetryService:
    service: TelemetryService | None = getattr(request.app.state, "telemetry_service", None)
    if service is None:
        raise SimRemapError("Telemetria desativada.", code="ROUTE_NOT_FOUND")
    return service


TelemetryDep = Annotated[TelemetryService, Depends(get_telemetry)]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


# --------------------------------------------------------------------------- E-26


@router.get(
    "/api/v1/telemetry/channels",
    summary="Catálogo de canais do veículo (E-26)",
    openapi_extra=_codes("VEHICLE_NOT_FOUND", "VALIDATION_FAILED"),
)
async def list_channels(
    service: TelemetryDep,
    vehicle_id: Annotated[str, Query(min_length=1, max_length=48)],
) -> list[TelemetryChannel]:
    del service
    from simremap.catalog.service import get_catalog  # noqa: PLC0415 - carga sob demanda

    vehicle = get_catalog().get_vehicle(vehicle_id)
    return list(catalog_for_vehicle(vehicle).channels)


# --------------------------------------------------------------------------- E-27


def _stream(chunks: Iterator[bytes], media: str, log_data: LogData, ext: str) -> StreamingResponse:
    run_id = log_data.header.run_id
    return StreamingResponse(
        chunks,
        media_type=media,
        headers={
            "X-Log-Sha256": log_data.sha256,
            "Content-Disposition": f'attachment; filename="run-{run_id}.{ext}"',
        },
    )


@router.get(
    "/api/v1/runs/{run_id}/log",
    summary="Export do log da puxada em JSON ou CSV (E-27)",
    response_model=None,
    openapi_extra=_codes(
        "RUN_NOT_FOUND",
        "LOG_NOT_FOUND",
        "LOG_NOT_READY",
        "VALIDATION_FAILED",
        "LOG_CORRUPTED",
        "STORAGE_FULL",
    ),
)
async def export_log(
    run_id: RunIdPath,
    service: TelemetryDep,
    format: Annotated[Literal["json", "csv"], Query()] = "json",
    channels: Annotated[str | None, Query(max_length=8000)] = None,
    decimate: Annotated[int, Query(ge=1, le=100)] = 1,
) -> StreamingResponse:
    data = await service.load_log(run_id, run=True)
    if format == "csv":
        names = [c.strip() for c in channels.split(",") if c.strip()] if channels else None
        select_channels(data, names)  # 422 antes de começar o streaming
        return _stream(iter_csv(data, names, decimate), "text/csv; charset=utf-8", data, "csv")
    return _stream(iter_json(data), "application/json", data, "json")


# --------------------------------------------------------------------------- E-28


@router.post(
    "/api/v1/logs/import",
    status_code=201,
    summary="Importa um DataLog JSON (E-28)",
    dependencies=[body_limit(MAX_IMPORT_BYTES)],
    response_model=DataLogSummary,
    openapi_extra=_codes(
        "LOG_ALREADY_IMPORTED",
        "PAYLOAD_TOO_LARGE",
        "UNSUPPORTED_MEDIA_TYPE",
        "LOG_SCHEMA_INVALID",
        "LOG_FORMAT_UNSUPPORTED",
        "LOG_HASH_MISMATCH",
        "STORAGE_FULL",
    ),
)
async def import_log(request: Request, service: TelemetryDep) -> JSONResponse:
    media = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise SimRemapError(
            f"Content-Type {media or 'ausente'!r} não aceite; use application/json.",
            code="UNSUPPORTED_MEDIA_TYPE",
        )
    repo = service.repository
    if repo is None:  # pragma: no cover - a app tem sempre banco
        raise SimRemapError("Banco indisponível.", code="DATABASE_UNAVAILABLE")
    body = await request.body()
    data = parse_import(body, request.headers.get("content-encoding"))
    existing = await repo.by_sha256(data.sha256)
    if existing is not None:
        raise telemetry_error(
            "LOG_ALREADY_IMPORTED",
            f"O log já existe com o log_id {existing.log_id}.",
            log_id=existing.log_id,
        )
    log_id = f"imp-{data.sha256[:12]}"
    await repo.save(data, log_id=log_id, source="imported")
    summary = summary_of(data)
    log.info("datalog.imported", log_id=log_id, sha256=data.sha256)
    return JSONResponse(
        summary.model_dump(mode="json"),
        status_code=201,
        headers={"Location": f"/api/v1/logs/{log_id}"},
    )


# --------------------------------------------------------------------------- E-29


async def _resolve(service: TelemetryService, ref: LogRef) -> LogData:
    if ref.run_id is not None:
        try:
            return await service.load_log(ref.run_id, run=True)
        except SimRemapError as exc:
            if exc.error_code == "RUN_NOT_FOUND":
                raise telemetry_error("LOG_NOT_FOUND", exc.detail, run_id=ref.run_id) from exc
            raise
    assert ref.log_id is not None  # noqa: S101 - LogRef exige um dos dois
    return await service.load_log(ref.log_id)


@router.post(
    "/api/v1/logs/compare",
    summary="Compara dois logs por bins de RPM (E-29)",
    openapi_extra=_codes(
        "LOG_NOT_FOUND",
        "LOG_NOT_READY",
        "LOG_COMPARE_NO_OVERLAP",
        "VALIDATION_FAILED",
        "LOG_CORRUPTED",
    ),
)
async def compare(body: LogCompareRequest, service: TelemetryDep) -> LogComparison:
    a = await _resolve(service, body.a)
    b = await _resolve(service, body.b)
    result = compare_logs(a, b, body)
    log.info("datalog.compare", a=result.a.log_id, b=result.b.log_id, bins=len(result.bins))
    return result


# --------------------------------------------------------------------------- WebSocket


async def telemetry_ws(websocket: WebSocket) -> None:
    """WebSocket de telemetria (rota Starlette: as dependências HTTP da app não se aplicam)."""
    app = websocket.app
    session_id = str(websocket.path_params.get("session_id", ""))
    service: TelemetryService | None = getattr(app.state, "telemetry_service", None)
    settings = getattr(app.state, "settings", None)
    origins = list(settings.cors_origins) if settings is not None else []
    idle = float(getattr(app.state, "telemetry_idle_timeout_s", 30.0))
    await serve_telemetry(
        websocket, service, session_id, allowed_origins=origins, idle_timeout_s=idle
    )


# A dependência global ``enforce_declared_body_limit`` ignora WebSocket; o endpoint fica como
# ``WebSocketRoute`` do Starlette (sem dependências HTTP), com o mesmo caminho do contrato.
router.routes.append(WebSocketRoute(WS_PATH, telemetry_ws, name="telemetry_ws"))
