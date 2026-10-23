"""Router da API REST para otimização de calibração via LAYA.ai."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Final

from fastapi import APIRouter, Body, Path, Request

from simremap.ai.contracts import AiTuneRequest, AiTuneResponse
from simremap.ai.service import AiTuningService
from simremap.api.deps import SessionDep
from simremap.catalog.service import CatalogService, get_catalog
from simremap.core.logging import get_logger
from simremap.ecu.errors import ecu_error
from simremap.ecu.repository import CalibrationRepository

TAG: Final = "ai-tuning"
logger = get_logger("simremap.ai.router")

router = APIRouter(prefix="/api/v1", tags=[TAG])

CalibrationIdPath = Annotated[str, Path(pattern=r"^[0-9a-z][-_0-9a-z]{0,63}$")]


def _codes(*codes: str) -> dict[str, Any]:
    return {"x-error-codes": list(codes)}


@router.post(
    "/calibrations/{calibration_id}/ai-tune",
    response_model=AiTuneResponse,
    summary="Otimiza tabelas da calibração via LAYA.ai",
    openapi_extra=_codes(
        "CALIBRATION_NOT_FOUND",
        "VEHICLE_NOT_FOUND",
        "DATABASE_UNAVAILABLE",
    ),
)
async def ai_tune_calibration(
    calibration_id: CalibrationIdPath,
    body: Annotated[AiTuneRequest, Body()],
    session: SessionDep,
    request: Request,
) -> AiTuneResponse:
    """Executa a otimização assistida por IA nas tabelas solicitadas."""
    repo = CalibrationRepository(session)
    calib = await repo.get(calibration_id)
    if calib is None:
        raise ecu_error("CALIBRATION_NOT_FOUND", calibration_id=calibration_id)

    catalog: CatalogService = getattr(request.app.state, "catalog", None) or get_catalog()
    try:
        vehicle = catalog.get_vehicle(calib.vehicle_id)
    except Exception:
        raise ecu_error("VEHICLE_NOT_FOUND", vehicle_id=calib.vehicle_id) from None

    stock_fuel = getattr(vehicle, "stock_fuel_id", "e100")

    service = AiTuningService(catalog)
    return await asyncio.to_thread(service.tune_calibration, calib, body, fuel_id=stock_fuel)
