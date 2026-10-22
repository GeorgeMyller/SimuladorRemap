"""Endpoints E-03 a E-05 do catálogo (rest-api 3.2; vehicle-catalog RF-14 a RF-17, RF-29).

- ``GET /api/v1/vehicles?include_drafts=false`` → ``VehicleListResponse``.
- ``GET /api/v1/vehicles/{vehicle_id}`` → ``VehicleDetail`` (``draft`` também devolve 200).
- ``GET /api/v1/vehicles/{vehicle_id}/reference-curves?fuel_id=&calibration_ref=stock``
  → ``ReferenceCurveListResponse`` com ``benchmark_id`` e ``benchmark_sha256``.
- ``GET /api/v1/upgrades`` → ``UpgradeCatalogResponse`` (oficina de upgrades, 002 RF-13).

Os 3 respondem com ``ETag: "<catalog_sha256>"`` (etiqueta forte entre aspas, RFC 9110) e
``Cache-Control: no-cache``; ``If-None-Match`` igual (com ou sem aspas, ``W/`` ou ``*``)
devolve 304 sem corpo. O ``vehicle_id`` nunca vira caminho de arquivo: o catálogo está em
memória e o slug é validado antes do lookup (``VEHICLE_ID_INVALID``, 422).
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from simremap.catalog.contracts import (
    CatalogFuelId,
    ReferenceCurveListResponse,
    VehicleDetail,
    VehicleListResponse,
)
from simremap.catalog.service import CatalogService, get_catalog
from simremap.catalog.upgrades import UpgradeCatalogResponse, upgrade_catalog
from simremap.core.errors import PROBLEM_JSON, ProblemDetail

__all__ = ["TAG", "router"]

TAG: Final = "vehicle-catalog"
router = APIRouter(prefix="/api/v1", tags=[TAG])

_ERRORS: Final[dict[int | str, dict[str, Any]]] = {
    304: {"description": "Não modificado (`If-None-Match` igual ao `ETag`)"},
    "4XX": {"model": ProblemDetail, "content": {PROBLEM_JSON: {}}, "description": "Erro"},
}


def _catalog() -> CatalogService:
    return get_catalog()


CatalogDep = Annotated[CatalogService, Depends(_catalog)]


def _etag(catalog: CatalogService) -> str:
    return f'"{catalog.catalog_sha256}"'


def _not_modified(request: Request, catalog: CatalogService) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    for raw in header.split(","):
        tag = raw.strip().removeprefix("W/").strip().strip('"')
        if tag in ("*", catalog.catalog_sha256):
            return True
    return False


def _respond(request: Request, catalog: CatalogService, body: bytes | None) -> Response:
    headers = {"ETag": _etag(catalog), "Cache-Control": "no-cache"}
    if body is None:
        return Response(status_code=304, headers=headers)
    return Response(content=body, media_type="application/json", headers=headers)


@router.get(
    "/vehicles",
    response_model=VehicleListResponse,
    responses=_ERRORS,
    summary="Lista os veículos do catálogo",
)
async def list_vehicles(
    request: Request,
    catalog: CatalogDep,
    include_drafts: Annotated[bool, Query(description="inclui veículos em draft")] = False,
) -> Response:
    if _not_modified(request, catalog):
        return _respond(request, catalog, None)
    body = catalog.cached_json(
        ("list", str(include_drafts)), lambda: catalog.vehicle_list_response(include_drafts)
    )
    return _respond(request, catalog, body)


@router.get(
    "/vehicles/{vehicle_id}",
    response_model=VehicleDetail,
    responses=_ERRORS,
    summary="Detalhe completo de um veículo",
)
async def get_vehicle(request: Request, catalog: CatalogDep, vehicle_id: str) -> Response:
    body = catalog.cached_json(  # 422/404 antes do 304
        ("detail", vehicle_id), lambda: catalog.get_vehicle_detail(vehicle_id)
    )
    if _not_modified(request, catalog):
        return _respond(request, catalog, None)
    return _respond(request, catalog, body)


@router.get(
    "/vehicles/{vehicle_id}/reference-curves",
    response_model=ReferenceCurveListResponse,
    responses=_ERRORS,
    summary="Curvas do Reference Benchmark Baseline v1 de um veículo",
)
async def get_reference_curves(
    request: Request,
    catalog: CatalogDep,
    vehicle_id: str,
    fuel_id: Annotated[CatalogFuelId | None, Query()] = None,
    calibration_ref: Annotated[str, Query(min_length=1, max_length=64)] = "stock",
) -> Response:
    body = catalog.cached_json(
        ("curves", vehicle_id, fuel_id or "", calibration_ref),
        lambda: catalog.reference_curve_response(vehicle_id, fuel_id, calibration_ref),
    )
    if _not_modified(request, catalog):
        return _respond(request, catalog, None)
    return _respond(request, catalog, body)


@router.get(
    "/upgrades",
    response_model=UpgradeCatalogResponse,
    summary="Catálogo de peças da oficina de upgrades",
)
async def list_upgrades() -> UpgradeCatalogResponse:
    return upgrade_catalog()
