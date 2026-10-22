"""``CatalogService``: fachada imutável do catálogo para os outros componentes (seção 8).

Ciclo de vida: a etapa ``startup.catalog`` do lifespan (``api/main.py``) chama
``startup_catalog(settings)`` depois de ``startup.cache`` e antes de ``startup.worker_host``
e ``startup.routers``; em erro, ``CatalogInvalid`` vira ``StartupError`` com
``code = CATALOG_INVALID`` e o processo termina com o código 4.
``get_catalog()`` devolve a instância carregada; se ninguém a carregou ainda
(ex.: testes sem lifespan), carrega-a uma vez a partir de ``SIMREMAP_CATALOG_DIR``.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from simremap.catalog.contracts import (
    VEHICLE_ID_PATTERN,
    FuelSpec,
    ReferenceCommandSchedule,
    ReferenceCurve,
    ReferenceCurveListResponse,
    VehicleDetail,
    VehicleListResponse,
    VehicleSpec,
    VehicleSummary,
)
from simremap.catalog.errors import (
    CatalogInvalid,
    FuelNotAllowed,
    FuelNotFound,
    ReferenceCurveNotFound,
    VehicleIdInvalid,
    VehicleNotFound,
    VehicleNotValidated,
)
from simremap.catalog.loader import Catalog, VehicleEntry, load_catalog_data
from simremap.catalog.settings import CatalogSettings
from simremap.core.config import Settings
from simremap.core.errors import SimRemapError
from simremap.core.logging import get_logger

__all__ = [
    "CatalogService",
    "get_catalog",
    "load_catalog",
    "reset_catalog",
    "set_catalog",
    "startup_catalog",
]

logger = get_logger("simremap.catalog")

_VEHICLE_ID_RE: Final = re.compile(VEHICLE_ID_PATTERN)
_DRAFT_DETAIL: Final = "veículo em validação, previsto para o Sprint 4"


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple | list):
        return [_thaw(v) for v in value]
    return value


class CatalogService:
    """Instância única criada no arranque; imutável após a carga."""

    def __init__(self, catalog: Catalog, *, allow_drafts: bool = False) -> None:
        self._catalog = catalog
        self.allow_drafts = allow_drafts
        self._details: dict[str, VehicleDetail] = {}
        self._json: dict[tuple[str, ...], bytes] = {}
        self._lock = threading.Lock()

    def cached_json(self, key: tuple[str, ...], build: Callable[[], BaseModel]) -> bytes:
        """Corpo JSON pré-serializado por ``key`` (RNF-02); erros não ficam em cache."""
        body = self._json.get(key)
        if body is None:
            body = build().model_dump_json().encode("utf-8")
            with self._lock:
                self._json.setdefault(key, body)
        return body

    # ------------------------------------------------------------ metadados
    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def catalog_version(self) -> str:
        return self._catalog.catalog_version

    @property
    def catalog_sha256(self) -> str:
        return self._catalog.catalog_sha256

    @property
    def benchmark_sha256(self) -> str:
        return self._catalog.benchmark_sha256

    @property
    def vehicle_ids(self) -> tuple[str, ...]:
        return tuple(self._catalog.vehicles)

    # ------------------------------------------------------------ veículos
    def _entry(self, vehicle_id: str) -> VehicleEntry:
        if not _VEHICLE_ID_RE.fullmatch(vehicle_id) or len(vehicle_id) > 48:  # noqa: PLR2004
            raise VehicleIdInvalid(
                f"O identificador {vehicle_id[:64]!r} não segue o padrão de slug de veículo.",
                vehicle_id=vehicle_id[:64],
            )
        entry = self._catalog.vehicles.get(vehicle_id)
        if entry is None:
            raise VehicleNotFound(
                f"O veículo {vehicle_id} não existe no catálogo.", vehicle_id=vehicle_id
            )
        return entry

    def list_vehicles(self, include_drafts: bool = False) -> list[VehicleSummary]:
        result = []
        for entry in self._catalog.vehicles.values():
            spec = entry.spec
            if spec.validation_status != "validated" and not include_drafts:
                continue
            result.append(
                VehicleSummary(
                    vehicle_id=spec.vehicle_id,
                    display_name=spec.display_name,
                    architecture_note=spec.architecture_note,
                    body=spec.body,
                    induction=spec.induction,
                    n_cyl=spec.engine.n_cyl,
                    displacement_cc=spec.engine.displacement_cc,
                    stock_fuel_id=spec.stock_fuel_id,
                    stock_profile_id=spec.stock_profile_id,
                    rated=spec.rated,
                    validation_status=spec.validation_status,
                    data_version=spec.data_version,
                )
            )
        return result

    def vehicle_list_response(self, include_drafts: bool = False) -> VehicleListResponse:
        return VehicleListResponse(
            catalog_version=self.catalog_version,
            catalog_sha256=self.catalog_sha256,
            items=self.list_vehicles(include_drafts),
        )

    def get_vehicle(self, vehicle_id: str) -> VehicleSpec:
        """``VEHICLE_ID_INVALID`` (422) ou ``VEHICLE_NOT_FOUND`` (404)."""
        return self._entry(vehicle_id).spec

    def get_vehicle_detail(self, vehicle_id: str) -> VehicleDetail:
        entry = self._entry(vehicle_id)
        with self._lock:
            cached = self._details.get(vehicle_id)
            if cached is None:
                spec = entry.spec
                data = {
                    name: getattr(spec, name) for name in VehicleSpec.model_fields
                }  # modelos já validados, partilhados por referência
                cached = VehicleDetail.model_validate(
                    {
                        **data,
                        "estimated_fields": list(entry.estimated_fields),
                        "data_sha256": entry.data_sha256,
                        "catalog_version": self.catalog_version,
                        "fuels": [self._catalog.fuels[f] for f in spec.allowed_fuel_ids],
                    }
                )
                self._details[vehicle_id] = cached
        return cached

    def estimated_fields(self, vehicle_id: str) -> list[str]:
        return list(self._entry(vehicle_id).estimated_fields)

    def data_sha256(self, vehicle_id: str) -> str:
        return self._entry(vehicle_id).data_sha256

    def get_for_session(self, vehicle_id: str) -> VehicleSpec:
        """Veículo para criar sessão: ``draft`` só com ``SIMREMAP_CATALOG_ALLOW_DRAFTS``."""
        spec = self._entry(vehicle_id).spec
        if spec.validation_status != "validated":
            if not self.allow_drafts:
                raise VehicleNotValidated(_DRAFT_DETAIL, vehicle_id=vehicle_id)
            logger.info("catalog.draft_used", vehicle_id=vehicle_id)
        return spec

    def stock_calibration_id(self, vehicle_id: str) -> str:
        return self._entry(vehicle_id).spec.stock_calibration_id

    def get_reference_command_schedule(self, vehicle_id: str) -> ReferenceCommandSchedule:
        return self._entry(vehicle_id).spec.reference_command_schedule

    def get_factory_calibration_payload(self, vehicle_id: str, profile_id: str) -> dict[str, Any]:
        """Cópia do payload ``Calibration`` de fábrica do perfil (``source = oem_stock``)."""
        entry = self._entry(vehicle_id)
        payload = entry.calibrations.get(profile_id)
        if payload is None:
            raise SimRemapError(
                f"O veículo {vehicle_id} não tem calibração de fábrica para {profile_id}.",
                code="RESOURCE_NOT_FOUND",
            )
        result: dict[str, Any] = _thaw(payload)
        return result

    def factory_calibrations(self, vehicle_id: str) -> dict[str, dict[str, Any]]:
        entry = self._entry(vehicle_id)
        return {pid: _thaw(p) for pid, p in entry.calibrations.items()}

    # ------------------------------------------------------------ combustíveis
    def get_fuel(self, fuel_id: str) -> FuelSpec:
        fuel = self._catalog.fuels.get(fuel_id)
        if fuel is None:
            raise FuelNotFound(f"O combustível {fuel_id[:32]!r} não existe.", fuel_id=fuel_id[:32])
        return fuel

    def allowed_fuels(self, vehicle_id: str) -> list[FuelSpec]:
        spec = self._entry(vehicle_id).spec
        return [self._catalog.fuels[f] for f in spec.allowed_fuel_ids]

    def get_fuel_for_vehicle(self, vehicle_id: str, fuel_id: str) -> FuelSpec:
        """``FUEL_NOT_ALLOWED`` (409) com ``allowed_fuel_ids`` quando fora da lista (EC-15)."""
        spec = self._entry(vehicle_id).spec
        fuel = self.get_fuel(fuel_id)
        if fuel.fuel_id not in spec.allowed_fuel_ids:
            allowed = list(spec.allowed_fuel_ids)
            raise FuelNotAllowed(
                f"O combustível {fuel_id} não é permitido no veículo {vehicle_id}; "
                f"permitidos: {', '.join(allowed)}.",
                vehicle_id=vehicle_id,
                fuel_id=fuel_id,
                allowed_fuel_ids=allowed,
            )
        return fuel

    # ------------------------------------------------------------ curvas
    def get_reference_curves(
        self, vehicle_id: str, fuel_id: str | None = None, calibration_ref: str = "stock"
    ) -> list[ReferenceCurve]:
        entry = self._entry(vehicle_id)
        curves = [
            c
            for c in entry.curves
            if c.calibration_ref == calibration_ref and (fuel_id is None or c.fuel_id == fuel_id)
        ]
        if not curves:
            raise ReferenceCurveNotFound(
                f"Nenhuma curva de referência para {vehicle_id} com calibration_ref="
                f"{calibration_ref[:64]!r}" + (f" e fuel_id={fuel_id!r}." if fuel_id else "."),
                vehicle_id=vehicle_id,
            )
        return curves

    def reference_curve_response(
        self, vehicle_id: str, fuel_id: str | None = None, calibration_ref: str = "stock"
    ) -> ReferenceCurveListResponse:
        return ReferenceCurveListResponse(
            vehicle_id=vehicle_id,
            catalog_sha256=self.catalog_sha256,
            benchmark_sha256=self.benchmark_sha256,
            items=self.get_reference_curves(vehicle_id, fuel_id, calibration_ref),
        )

    def all_reference_curves(self) -> Sequence[ReferenceCurve]:
        return [c for entry in self._catalog.vehicles.values() for c in entry.curves]


# --------------------------------------------------------------------------- instância única

_SERVICE: CatalogService | None = None
_SERVICE_LOCK: Final = threading.Lock()


def load_catalog(
    root: Path | None = None,
    *,
    allow_drafts: bool | None = None,
    env: str | None = None,
    require_canonical: bool = True,
) -> CatalogService:
    """Carrega o catálogo (``root`` ou ``SIMREMAP_CATALOG_DIR``) e fixa a instância única."""
    global _SERVICE  # noqa: PLW0603 - instância única do processo (seção 8)
    cfg = CatalogSettings()
    catalog = load_catalog_data(
        root if root is not None else cfg.resolved_dir, require_canonical=require_canonical
    )
    drafts = cfg.allow_drafts(env) if allow_drafts is None else allow_drafts
    service = CatalogService(catalog, allow_drafts=drafts)
    with _SERVICE_LOCK:
        _SERVICE = service
    return service


def get_catalog() -> CatalogService:
    """Instância carregada; carrega uma vez sob demanda se o arranque ainda não o fez."""
    service = _SERVICE
    if service is not None:
        return service
    with _SERVICE_LOCK:
        if _SERVICE is not None:
            return _SERVICE
    return load_catalog()


def set_catalog(service: CatalogService | None) -> None:
    """Substitui a instância única (testes e lifespan)."""
    global _SERVICE  # noqa: PLW0603
    with _SERVICE_LOCK:
        _SERVICE = service


def reset_catalog() -> None:
    set_catalog(None)


def startup_catalog(settings: Settings | None = None) -> CatalogService:
    """Etapa ``startup.catalog`` do lifespan; ``CatalogInvalid`` (saída 4) em erro.

    Com ``settings``, usa ``Settings.catalog_dir`` e ``Settings.catalog_drafts_allowed``;
    sem ele, as variáveis ``SIMREMAP_CATALOG_*`` lidas por ``CatalogSettings``.
    """
    env = settings.env if settings is not None else None
    root = settings.catalog_dir if settings is not None else None
    drafts = settings.catalog_drafts_allowed if settings is not None else None
    try:
        service = load_catalog(root, allow_drafts=drafts, env=env)
    except CatalogInvalid as exc:
        logger.error(
            "startup.failed",
            code="CATALOG_INVALID",
            exit_code=exc.exit_code,
            issues=[issue.as_log() for issue in exc.issues[:50]],
            issue_count=len(exc.issues),
        )
        raise
    validated = sum(
        1 for e in service.catalog.vehicles.values() if e.spec.validation_status == "validated"
    )
    logger.info(
        "startup.catalog",
        vehicles=len(service.vehicle_ids),
        validated=validated,
        catalog_version=service.catalog_version,
        catalog_sha256=service.catalog_sha256,
        duration_ms=round(service.catalog.load_ms, 1),
        allow_drafts=service.allow_drafts,
    )
    return service
