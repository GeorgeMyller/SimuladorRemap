"""Oficina de upgrades: catálogo fixo de peças e ``apply_upgrades`` (002 RF-13 a RF-17; D-07).

``apply_upgrades(vehicle, pacote)`` é uma transformação pura: devolve um ``VehicleSpec``
novo (``model_copy`` + revalidação completa, os validadores do catálogo continuam a valer)
e as escalas da física que não pertencem ao veículo (``PhysicsOverrides``: contrapressão do
escape e capacidade da bomba). Física, dano e ECU OEM enxergam o mesmo veículo modificado.

Peças por categoria (``stock`` é sempre a peça de série):

- ``turbo`` (``TURBO_STAGES``; mais fluxo no topo, mais lag em baixo):

  ========  ==========  ===============  ========  ======  ========  ==========
  peça      turbina     compressor       m_range   n_peak  inércia   wastegate
  ========  ==========  ===============  ========  ======  ========  ==========
  upgraded  ×1,25       ×1,30            ×1,15     ×1,10   ×1,45     ×1,00
  stage2    ×1,45       ×1,60            ×1,25     ×1,15   ×1,90     ×1,15
  stage3    ×1,70       ×2,00            ×1,35     ×1,20   ×2,60     ×1,30
  ========  ==========  ===============  ========  ======  ========  ==========

  ("compressor" = ``m_choke_max`` e ``m_peak``; ``upgraded`` é o Stage 1);
- ``injectors.high_flow``: vazão estática ×1,5;
- ``fuel_pump.high_flow``: ``fuel_pump_capacity_scale`` 1,8;
- ``intercooler.sport``: efetividade +0,08 (teto 0,95);
- ``downpipe.high_flow``: ``exhaust_backpressure_scale`` 0,6;
- ``internals.forged``: carga da biela e torque sustentado ×1,35, pressão de cilindro
  ×1,25 e temperatura do pistão +40 °C.

``turbo`` sem turbo e ``intercooler`` sem intercooler ⇒ 422 ``UPGRADE_NOT_COMPATIBLE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, NoReturn

from pydantic import Field

from simremap.catalog.contracts import (
    CompressorMapSpec,
    IntercoolerSpec,
    MechanicalLimits,
    TurboSpec,
    VehicleSpec,
)
from simremap.catalog.errors import UpgradeNotCompatible
from simremap.core.contracts import ContractModel

__all__ = [
    "TURBO_STAGES",
    "UPGRADE_CATEGORIES",
    "PhysicsOverrides",
    "TurboStage",
    "UpgradeCatalogResponse",
    "UpgradeCategory",
    "UpgradeCategoryOptions",
    "UpgradeOption",
    "UpgradePackage",
    "UpgradeResult",
    "apply_upgrades",
    "upgrade_catalog",
]

UpgradeCategory = Literal["turbo", "injectors", "fuel_pump", "intercooler", "downpipe", "internals"]
UPGRADE_CATEGORIES: Final[tuple[UpgradeCategory, ...]] = (
    "turbo",
    "injectors",
    "fuel_pump",
    "intercooler",
    "downpipe",
    "internals",
)

TurboPart = Literal["upgraded", "stage2", "stage3"]


@dataclass(frozen=True, slots=True)
class TurboStage:
    """Escalas de uma turbina maior sobre a de série."""

    label: str
    turbine_area: float
    compressor_flow: float  # m_choke_max e m_peak
    compressor_range: float
    compressor_n_peak: float
    rotor_inertia: float
    wastegate_area: float


TURBO_STAGES: Final[dict[TurboPart, TurboStage]] = {
    "upgraded": TurboStage("Turbina upgraded (Stage 1)", 1.25, 1.30, 1.15, 1.10, 1.45, 1.0),
    "stage2": TurboStage("Turbina Stage 2", 1.45, 1.60, 1.25, 1.15, 1.90, 1.15),
    "stage3": TurboStage("Turbina Stage 3", 1.70, 2.00, 1.35, 1.20, 2.60, 1.30),
}
INJECTOR_FLOW_SCALE: Final = 1.5
FUEL_PUMP_CAPACITY_SCALE: Final = 1.8
INTERCOOLER_EFFECTIVENESS_ADD: Final = 0.08
INTERCOOLER_EFFECTIVENESS_MAX: Final = 0.95
DOWNPIPE_BACKPRESSURE_SCALE: Final = 0.6
FORGED_ROD_SCALE: Final = 1.35  # max_rod_load_kn e rod_torque_limit_nm
FORGED_PRESSURE_SCALE: Final = 1.25
FORGED_PISTON_TEMP_ADD_C: Final = 40.0


class UpgradePackage(ContractModel):
    """Peças escolhidas na criação da sessão (padrão: tudo de série)."""

    turbo: Literal["stock", "upgraded", "stage2", "stage3"] = "stock"
    injectors: Literal["stock", "high_flow"] = "stock"
    fuel_pump: Literal["stock", "high_flow"] = "stock"
    intercooler: Literal["stock", "sport"] = "stock"
    downpipe: Literal["stock", "high_flow"] = "stock"
    internals: Literal["stock", "forged"] = "stock"

    @property
    def is_stock(self) -> bool:
        return all(getattr(self, category) == "stock" for category in UPGRADE_CATEGORIES)

    def non_stock(self) -> dict[str, str]:
        """Categorias com peça diferente da de série (para log e auditoria)."""
        parts = {category: str(getattr(self, category)) for category in UPGRADE_CATEGORIES}
        return {category: part for category, part in parts.items() if part != "stock"}


class PhysicsOverrides(ContractModel):
    """Escalas da física fora do ``VehicleSpec`` (campos de ``PhysicsConfig``)."""

    exhaust_backpressure_scale: float = Field(1.0, ge=0.3, le=1.0)  # (-)
    fuel_pump_capacity_scale: float = Field(1.0, ge=1.0, le=3.0)  # (-)


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    vehicle: VehicleSpec
    physics: PhysicsOverrides


class UpgradeOption(ContractModel):
    part_id: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=60)
    effects: dict[str, float] = Field(default_factory=dict)  # parâmetro → fator ou soma


class UpgradeCategoryOptions(ContractModel):
    category: UpgradeCategory
    options: list[UpgradeOption] = Field(min_length=1)


class UpgradeCatalogResponse(ContractModel):
    """Resposta de ``GET /api/v1/upgrades``."""

    categories: list[UpgradeCategoryOptions]


_STOCK: Final = UpgradeOption(part_id="stock", label="Série")


def _turbo_option(part: TurboPart, stage: TurboStage) -> UpgradeOption:
    effects = {
        "turbine_area_eff_scale": stage.turbine_area,
        "compressor_flow_scale": stage.compressor_flow,
        "compressor_n_peak_scale": stage.compressor_n_peak,
        "rotor_inertia_scale": stage.rotor_inertia,
    }
    if stage.wastegate_area != 1.0:
        effects["wastegate_area_scale"] = stage.wastegate_area
    return UpgradeOption(part_id=part, label=stage.label, effects=effects)


_CATALOG: Final = UpgradeCatalogResponse(
    categories=[
        UpgradeCategoryOptions(
            category="turbo",
            options=[_STOCK, *(_turbo_option(part, stage) for part, stage in TURBO_STAGES.items())],
        ),
        UpgradeCategoryOptions(
            category="injectors",
            options=[
                _STOCK,
                UpgradeOption(
                    part_id="high_flow",
                    label="Bicos de alta vazão",
                    effects={"injector_flow_scale": INJECTOR_FLOW_SCALE},
                ),
            ],
        ),
        UpgradeCategoryOptions(
            category="fuel_pump",
            options=[
                _STOCK,
                UpgradeOption(
                    part_id="high_flow",
                    label="Bomba de combustível de alta vazão",
                    effects={"fuel_pump_capacity_scale": FUEL_PUMP_CAPACITY_SCALE},
                ),
            ],
        ),
        UpgradeCategoryOptions(
            category="intercooler",
            options=[
                _STOCK,
                UpgradeOption(
                    part_id="sport",
                    label="Intercooler esportivo",
                    effects={"intercooler_effectiveness_add": INTERCOOLER_EFFECTIVENESS_ADD},
                ),
            ],
        ),
        UpgradeCategoryOptions(
            category="downpipe",
            options=[
                _STOCK,
                UpgradeOption(
                    part_id="high_flow",
                    label="Downpipe de alto fluxo",
                    effects={"exhaust_backpressure_scale": DOWNPIPE_BACKPRESSURE_SCALE},
                ),
            ],
        ),
        UpgradeCategoryOptions(
            category="internals",
            options=[
                _STOCK,
                UpgradeOption(
                    part_id="forged",
                    label="Internos forjados",
                    effects={
                        "max_rod_load_scale": FORGED_ROD_SCALE,
                        "rod_torque_limit_scale": FORGED_ROD_SCALE,
                        "max_cylinder_pressure_scale": FORGED_PRESSURE_SCALE,
                        "max_piston_temp_add_c": FORGED_PISTON_TEMP_ADD_C,
                    },
                ),
            ],
        ),
    ]
)


def upgrade_catalog() -> UpgradeCatalogResponse:
    """Catálogo fixo das 6 categorias de peças."""
    return _CATALOG


def _incompatible(vehicle: VehicleSpec, category: str, part_id: str, reason: str) -> NoReturn:
    raise UpgradeNotCompatible(
        f"A peça {category}.{part_id} não serve no veículo {vehicle.vehicle_id}: {reason}.",
        category=category,
        part_id=part_id,
        vehicle_id=vehicle.vehicle_id,
    )


def _upgraded_compressor(spec: CompressorMapSpec, stage: TurboStage) -> CompressorMapSpec:
    return spec.model_copy(
        update={
            "m_choke_max_kg_s": min(spec.m_choke_max_kg_s * stage.compressor_flow, 1.5),
            "m_peak_kg_s": min(spec.m_peak_kg_s * stage.compressor_flow, 1.2),
            "m_range_kg_s": min(spec.m_range_kg_s * stage.compressor_range, 1.0),
            "n_peak_rpm": min(spec.n_peak_rpm * stage.compressor_n_peak, spec.n_max_rpm),
        }
    )


def _upgraded_turbo(turbo: TurboSpec, stage: TurboStage) -> TurboSpec:
    return turbo.model_copy(
        update={
            "turbine_area_eff_cm2": min(turbo.turbine_area_eff_cm2 * stage.turbine_area, 40.0),
            "rotor_inertia_kg_m2": min(turbo.rotor_inertia_kg_m2 * stage.rotor_inertia, 5e-4),
            "wastegate_area_max_cm2": min(
                turbo.wastegate_area_max_cm2 * stage.wastegate_area, 20.0
            ),
            "compressor": _upgraded_compressor(turbo.compressor, stage),
        }
    )


def _sport_intercooler(intercooler: IntercoolerSpec) -> IntercoolerSpec:
    effectiveness = intercooler.effectiveness + INTERCOOLER_EFFECTIVENESS_ADD
    return intercooler.model_copy(
        update={"effectiveness": min(effectiveness, INTERCOOLER_EFFECTIVENESS_MAX)}
    )


def _forged_limits(limits: MechanicalLimits) -> MechanicalLimits:
    return limits.model_copy(
        update={
            "rod_torque_limit_nm": min(limits.rod_torque_limit_nm * FORGED_ROD_SCALE, 3000.0),
            "max_rod_load_kn": min(limits.max_rod_load_kn * FORGED_ROD_SCALE, 300.0),
            "max_cylinder_pressure_bar": min(
                limits.max_cylinder_pressure_bar * FORGED_PRESSURE_SCALE, 250.0
            ),
            "max_piston_temp_c": min(limits.max_piston_temp_c + FORGED_PISTON_TEMP_ADD_C, 450.0),
        }
    )


def _vehicle_updates(vehicle: VehicleSpec, pkg: UpgradePackage) -> dict[str, object]:
    updates: dict[str, object] = {}
    engine_updates: dict[str, object] = {}
    if pkg.turbo != "stock":
        if vehicle.turbo is None:
            _incompatible(vehicle, "turbo", pkg.turbo, "o motor não é turboalimentado")
        updates["turbo"] = _upgraded_turbo(vehicle.turbo, TURBO_STAGES[pkg.turbo])
    if pkg.intercooler == "sport":
        if vehicle.engine.intercooler is None:
            _incompatible(vehicle, "intercooler", pkg.intercooler, "o motor não tem intercooler")
        engine_updates["intercooler"] = _sport_intercooler(vehicle.engine.intercooler)
    if pkg.injectors == "high_flow":
        flow = min(vehicle.injectors.flow_cc_min * INJECTOR_FLOW_SCALE, 5000.0)
        updates["injectors"] = vehicle.injectors.model_copy(update={"flow_cc_min": flow})
    if pkg.internals == "forged":
        updates["mechanical_limits"] = _forged_limits(vehicle.mechanical_limits)
    if engine_updates:
        updates["engine"] = vehicle.engine.model_copy(update=engine_updates)
    return updates


def apply_upgrades(vehicle: VehicleSpec, pkg: UpgradePackage) -> UpgradeResult:
    """Veículo modificado (revalidado) e escalas da física do pacote ``pkg``."""
    physics = PhysicsOverrides(
        exhaust_backpressure_scale=(
            DOWNPIPE_BACKPRESSURE_SCALE if pkg.downpipe == "high_flow" else 1.0
        ),
        fuel_pump_capacity_scale=FUEL_PUMP_CAPACITY_SCALE if pkg.fuel_pump == "high_flow" else 1.0,
    )
    updates = _vehicle_updates(vehicle, pkg)
    if not updates:
        return UpgradeResult(vehicle=vehicle, physics=physics)
    modified = vehicle.model_copy(update=updates)
    # model_copy não valida: a revalidação garante os validadores do catálogo.
    return UpgradeResult(vehicle=VehicleSpec.model_validate(modified.model_dump()), physics=physics)
