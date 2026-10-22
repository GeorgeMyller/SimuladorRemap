"""Materialização idempotente das calibrações de série no arranque.

Fontes: data-model 6.3; catalog RF-20; D-04.

Para cada ficheiro ``vehicles/<vehicle_id>/calibrations/<profile_id>.json`` do catálogo
(formato de calibração exportada, file-formats seção 3, ``metadata.source = oem_stock``):

- se ``stock-<vehicle_id>-<profile_id>`` não existe ⇒ grava a versão 1;
- se existe e o ``content_hash`` do ficheiro difere do da última versão ⇒ grava uma
  versão nova (``source = oem_stock``);
- se o hash é igual ⇒ nada muda (idempotente).

Ficheiros inválidos são registados no log e ignorados (o loader do catálogo é quem
bloqueia o arranque com ``CATALOG_INVALID``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from simremap.core.logging import get_logger
from simremap.ecu.calibration import (
    CalibrationMetadata,
    compute_content_hash,
    parse_content,
)
from simremap.ecu.contracts import EcuValidationError
from simremap.ecu.repository import CalibrationRepository
from simremap.ecu.service import stock_calibration_id

__all__ = [
    "DEFAULT_CATALOG_DATA_DIR",
    "SeedReport",
    "StockCalibrationSource",
    "discover_stock_sources",
    "seed_stock_calibrations",
]

logger = get_logger("simremap.ecu.seed_stock")

DEFAULT_CATALOG_DATA_DIR = Path(__file__).resolve().parent.parent / "catalog" / "data"


@dataclass(frozen=True, slots=True)
class StockCalibrationSource:
    vehicle_id: str
    profile_id: str
    payload: dict[str, Any]
    origin: str = ""

    @property
    def calibration_id(self) -> str:
        return stock_calibration_id(self.vehicle_id, self.profile_id)


@dataclass(slots=True)
class SeedReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


def discover_stock_sources(
    data_dir: Path = DEFAULT_CATALOG_DATA_DIR,
) -> list[StockCalibrationSource]:
    """Lê ``vehicles/*/calibrations/*.json`` (ordem determinística por caminho)."""
    root = data_dir / "vehicles"
    if not root.is_dir():
        return []
    sources: list[StockCalibrationSource] = []
    for path in sorted(root.glob("*/calibrations/*.json")):
        vehicle_id = path.parent.parent.name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("ecu.seed_stock.unreadable", path=str(path), reason=type(exc).__name__)
            continue
        if isinstance(payload, dict):
            sources.append(StockCalibrationSource(vehicle_id, path.stem, payload, origin=str(path)))
    return sources


async def seed_stock_calibrations(
    sessionmaker: async_sessionmaker[AsyncSession], sources: Iterable[StockCalibrationSource]
) -> SeedReport:
    report = SeedReport()
    for src in sources:
        cal_id = src.calibration_id
        try:
            content = parse_content(
                {**src.payload, "vehicle_id": src.vehicle_id, "profile_id": src.profile_id}
            )
            meta_raw = dict(src.payload.get("metadata") or {})
            meta_raw.setdefault("name", f"Série {src.vehicle_id} {src.profile_id}")
            meta = CalibrationMetadata.model_validate({**meta_raw, "source": "oem_stock"})
        except (EcuValidationError, ValidationError, ValueError) as exc:
            code = exc.code if isinstance(exc, EcuValidationError) else "VALIDATION_FAILED"
            logger.error("ecu.seed_stock.invalid", calibration_id=cal_id, code=code)
            report.invalid.append(cal_id)
            continue
        async with sessionmaker() as session:
            repo = CalibrationRepository(session)
            if not await repo.exists(cal_id):
                await repo.create(content, meta, calibration_id=cal_id)
                report.created.append(cal_id)
                continue
            latest = await repo.get(cal_id)
            if latest.content_hash == compute_content_hash(content):
                report.unchanged.append(cal_id)
                continue
            await repo.replace(cal_id, latest.version, content, meta)
            report.updated.append(cal_id)
    if report.created or report.updated or report.invalid:
        logger.info(
            "ecu.seed_stock",
            created=len(report.created),
            updated=len(report.updated),
            unchanged=len(report.unchanged),
            invalid=len(report.invalid),
        )
    return report
