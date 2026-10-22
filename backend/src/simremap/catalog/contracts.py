"""Contratos do catálogo de veículos e combustíveis (vehicle-catalog seção 9).

Os dados vivem em arquivos JSON versionados (``catalog/data/``); estes modelos validam a
estrutura e as invariantes locais de cada arquivo. As validações que exigem outro arquivo
(hash do manifesto, curva × ``rev_limit_rpm``, calibração de fábrica) ficam no loader, que
converte os ``ValidationError`` em ``CATALOG_INVALID`` com ponteiro JSON.

Todos os modelos são imutáveis e recusam campos extra. Campos calculados
(``computed_field``) saem na serialização e são ignorados na validação, para que o
round-trip ``model_dump`` → ``model_validate`` funcione.
"""

from __future__ import annotations

import itertools
import math
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import ConfigDict, Field, computed_field, model_validator

from simremap.core.contracts import ContractModel, Sha256Hex

__all__ = [
    "BENCHMARK_ID",
    "CURVE_RPM_STEP",
    "DISPLACEMENT_TOLERANCE",
    "FLEX_FUEL_ID",
    "FUEL_IDS",
    "KW_PER_HP",
    "PROFILE_IDS",
    "VEHICLE_ID_PATTERN",
    "AxisName",
    "CatalogFuelId",
    "CatalogModel",
    "ChenFlynnSpec",
    "CompressorMapSpec",
    "EngineSpec",
    "FactoryCalibrationRef",
    "FuelId",
    "FuelSpec",
    "Grid1D",
    "Grid2D",
    "InjectorSpec",
    "IntercoolerSpec",
    "MechanicalLimits",
    "ProfileIdLiteral",
    "Provenance",
    "ProvenanceKind",
    "Quantity",
    "QuantityDeviation",
    "RatedFigures",
    "ReferenceCommandPoint",
    "ReferenceCommandSchedule",
    "ReferenceComparison",
    "ReferenceConditions",
    "ReferenceCurve",
    "ReferenceCurveListResponse",
    "ReferenceCurvePoint",
    "SuperchargerSpec",
    "TurboSpec",
    "VehicleDetail",
    "VehicleId",
    "VehicleListResponse",
    "VehicleSpec",
    "VehicleSummary",
    "VvtSpec",
]

VEHICLE_ID_PATTERN: Final = r"^[0-9a-z]+(-[0-9a-z]+){1,5}$"
BENCHMARK_ID: Final = "reference-benchmark-baseline-v1"
KW_PER_HP: Final = 0.7457
CURVE_RPM_STEP: Final = 250.0
CURVE_FIRST_RPM_MAX: Final = 3000.0
DISPLACEMENT_TOLERANCE: Final = 0.005
ROD_RATIO_MIN: Final = 2.8
ROD_RATIO_MAX: Final = 4.2

VehicleId = Annotated[str, Field(pattern=VEHICLE_ID_PATTERN, max_length=48)]
CatalogFuelId = Literal["e27", "e100", "podium", "e0"]  # combustíveis de catalog/data/fuels
FuelId = CatalogFuelId | Literal["flex"]  # flex = blend E27/E100 da sessão (fuel_blend)
ProfileIdLiteral = Literal["oem-stage", "ft-pro", "m1-race", "ht-elite"]  # igual a EcuProfileId
Quantity = Literal["torque_crank_nm", "power_wheel_kw", "lambda_value", "egt_c"]
AxisName = Literal["rpm", "map_kpa", "cam_deg", "battery_v", "dp_kpa", "pressure_ratio"]
Confidence = Literal["measured", "published", "estimated"]

FUEL_IDS: Final[tuple[str, ...]] = ("e27", "e100", "podium", "e0")  # combustíveis do catálogo
FLEX_FUEL_ID: Final = "flex"  # sintético (physics.fuel_blend), nunca em fuels/
PROFILE_IDS: Final[tuple[str, ...]] = ("oem-stage", "ft-pro", "m1-race", "ht-elite")


def _strictly_increasing(values: list[float]) -> bool:
    return all(b > a for a, b in itertools.pairwise(values))


def _all_finite(values: list[float]) -> bool:
    return all(math.isfinite(v) for v in values)


class CatalogModel(ContractModel):
    """Base dos contratos do catálogo (imutável, sem extra, ``str`` sem espaços nas pontas)."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        computed = cls.model_computed_fields
        if computed and isinstance(data, dict):
            return {key: value for key, value in data.items() if key not in computed}
        return data


class ProvenanceKind(StrEnum):
    PRD = "prd"  # valor exato da seção 7 do PRD
    PUBLIC_SPEC = "public_spec"  # ficha técnica pública da arquitetura de inspiração
    LITERATURE = "literature"  # Heywood ou outra literatura aberta
    DERIVED = "derived"  # calculado de outros campos (ex.: cilindrada)
    ESTIMATE = "estimate"  # inferido, a validar


class Provenance(CatalogModel):
    kind: ProvenanceKind
    note: str = Field("", max_length=300)
    # citação; obrigatória em public_spec/literature
    source: str | None = Field(None, max_length=300)

    @model_validator(mode="after")
    def _source_required(self) -> Self:
        needs_source = self.kind in (ProvenanceKind.PUBLIC_SPEC, ProvenanceKind.LITERATURE)
        if needs_source and not self.source:
            raise ValueError(f"proveniência '{self.kind.value}' exige 'source'")
        return self


class Grid1D(CatalogModel):
    """Curva 1D com interpolação linear e saturação nas bordas."""

    x_name: AxisName
    x_values: list[float] = Field(min_length=2, max_length=32)  # estritamente crescente
    values: list[float] = Field(min_length=2, max_length=32)  # len == len(x_values)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not _strictly_increasing(self.x_values):
            raise ValueError("x_values deve ser estritamente crescente")
        if len(self.values) != len(self.x_values):
            raise ValueError("values deve ter o mesmo comprimento de x_values")
        if not (_all_finite(self.x_values) and _all_finite(self.values)):
            raise ValueError("Grid1D aceita só valores finitos")
        return self


class Grid2D(CatalogModel):
    """Tabela 2D (linhas = y, colunas = x), interpolação bilinear com saturação."""

    x_name: AxisName  # colunas (ex.: rpm)
    x_values: list[float] = Field(min_length=2, max_length=32)
    y_name: AxisName  # linhas (ex.: map_kpa)
    y_values: list[float] = Field(min_length=2, max_length=32)
    z_values: list[list[float]]  # len(y) linhas × len(x) colunas

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not (_strictly_increasing(self.x_values) and _strictly_increasing(self.y_values)):
            raise ValueError("eixos de Grid2D devem ser estritamente crescentes")
        if len(self.z_values) != len(self.y_values):
            raise ValueError("z_values deve ter len(y_values) linhas")
        for row in self.z_values:
            if len(row) != len(self.x_values):
                raise ValueError("cada linha de z_values deve ter len(x_values) colunas")
            if not _all_finite(row):
                raise ValueError("Grid2D aceita só valores finitos")
        if not (_all_finite(self.x_values) and _all_finite(self.y_values)):
            raise ValueError("Grid2D aceita só valores finitos")
        return self


class VvtSpec(CatalogModel):
    intake_min_deg: float = Field(0.0, ge=-10.0, le=10.0)  # ° de cambota, + = avanço
    intake_max_deg: float = Field(..., ge=0.0, le=80.0)
    exhaust_min_deg: float | None = Field(None, ge=-10.0, le=10.0)  # None = sem VVT de escape
    exhaust_max_deg: float | None = Field(None, ge=0.0, le=80.0)
    actuator_tau_s: float = Field(0.15, ge=0.02, le=1.0)  # s
    k_vvt: float = Field(0.06, ge=0.0, le=0.20)  # ganho máximo de VE pelo VVT
    g_vvt: Grid2D  # x = rpm, y = cam_deg, valores −1..1

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.intake_max_deg <= self.intake_min_deg:
            raise ValueError("intake_max_deg deve ser maior que intake_min_deg")
        if (self.exhaust_min_deg is None) != (self.exhaust_max_deg is None):
            raise ValueError("exhaust_min_deg e exhaust_max_deg vêm juntos ou ausentes")
        if (
            self.exhaust_min_deg is not None
            and self.exhaust_max_deg is not None
            and self.exhaust_max_deg <= self.exhaust_min_deg
        ):
            raise ValueError("exhaust_max_deg deve ser maior que exhaust_min_deg")
        return self


class IntercoolerSpec(CatalogModel):
    kind: Literal["air_to_air", "air_to_water"]
    effectiveness: float = Field(0.75, ge=0.40, le=0.95)  # ε (-)
    k_dp_kpa_per_kgps2: float = Field(..., ge=0.0, le=200.0)  # Δp_ic = k · ṁ²


class ChenFlynnSpec(CatalogModel):
    c_bar: float = Field(0.25, ge=0.0, le=1.0)  # bar
    a: float = Field(0.005, ge=0.0, le=0.02)  # (-)
    b_bar_s_m: float = Field(0.09, ge=0.0, le=0.3)  # bar·s/m
    q_bar_s2_m2: float = Field(0.0009, ge=0.0, le=0.005)  # bar·s²/m²


class EngineSpec(CatalogModel):
    architecture: Literal["inline", "v"]
    n_cyl: int = Field(..., ge=3, le=8)
    v_angle_deg: float | None = Field(None, ge=45.0, le=120.0)  # obrigatório se "v"
    bore_mm: float = Field(..., ge=60.0, le=110.0)  # mm
    stroke_mm: float = Field(..., ge=60.0, le=110.0)  # mm
    rod_length_mm: float = Field(..., ge=100.0, le=200.0)  # mm
    compression_ratio: float = Field(..., ge=7.0, le=14.0)  # (-)
    displacement_cc: float = Field(..., ge=500.0, le=8000.0)  # cc, ±0,5 % da geometria
    valvetrain: Literal["sohc", "dohc", "ohv"]
    valves_per_cyl: Literal[2, 3, 4, 5]
    firing_order: list[int]  # permutação de 1..n_cyl, começa em 1
    ivc_deg_abdc: float = Field(..., ge=0.0, le=90.0)  # ° após PMI, VVT a 0
    evo_deg_bbdc: float = Field(..., ge=0.0, le=90.0)  # ° antes do PMI
    vvt: VvtSpec | None = None
    injection_type: Literal["gdi", "pfi"]
    throttle_diameter_mm: float = Field(..., ge=30.0, le=120.0)  # mm
    throttle_location: Literal["post_compressor", "pre_compressor"] = "post_compressor"
    intake_manifold_volume_l: float = Field(..., gt=0.5, le=20.0)  # L
    boost_volume_l: float | None = Field(None, gt=0.5, le=20.0)  # L; None em pre_compressor
    exhaust_manifold_volume_l: float = Field(..., gt=0.2, le=10.0)  # L
    intercooler: IntercoolerSpec | None = None
    recip_mass_g: float = Field(..., ge=200.0, le=1500.0)  # g
    true_ve: Grid2D  # x = rpm, y = map_kpa, 0,20..1,35
    mbt_reference: Grid2D | None = None  # só UI, ° BTDC
    wiebe_duration_ref_deg: float = Field(55.0, ge=30.0, le=90.0)  # °
    wiebe_rpm_ref: float = Field(3000.0, ge=1000.0, le=8000.0)  # rev/min
    friction: ChenFlynnSpec = Field(default_factory=ChenFlynnSpec)
    crank_trigger: Literal["60-2", "36-1", "36-2", "24-1"] = "60-2"
    cam_sync: Literal["1x", "4x", "none"] = "1x"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def calc_displacement_cc(self) -> float:
        """Cilindrada geométrica ``(π/4)·B²·S·n_cyl`` em cc."""
        return math.pi / 4 * (self.bore_mm / 10) ** 2 * (self.stroke_mm / 10) * self.n_cyl

    @model_validator(mode="after")
    def _check_geometry(self) -> Self:
        calc = self.calc_displacement_cc
        if abs(self.displacement_cc - calc) > DISPLACEMENT_TOLERANCE * calc:
            raise ValueError(
                f"displacement_cc {self.displacement_cc} difere da geometria ({calc:.1f} cc) "
                "acima de 0,5 %"
            )
        rod_ratio = self.rod_length_mm / (self.stroke_mm / 2)
        if not ROD_RATIO_MIN <= rod_ratio <= ROD_RATIO_MAX:
            raise ValueError(f"relação biela/manivela {rod_ratio:.2f} fora de 2,8..4,2")
        if sorted(self.firing_order) != list(range(1, self.n_cyl + 1)):
            raise ValueError("firing_order deve ser uma permutação de 1..n_cyl")
        if self.firing_order[0] != 1:
            raise ValueError("firing_order deve começar no cilindro 1")
        if (self.architecture == "v") != (self.v_angle_deg is not None):
            raise ValueError("v_angle_deg é obrigatório em 'v' e proibido em 'inline'")
        for row in self.true_ve.z_values:
            if any(not 0.20 <= v <= 1.35 for v in row):  # noqa: PLR2004
                raise ValueError("true_ve deve ficar entre 0,20 e 1,35")
        return self


class CompressorMapSpec(CatalogModel):
    """Forma paramétrica do mapa do compressor (engine-physics-core A.8)."""

    pr_design: float = Field(..., ge=1.5, le=4.5)  # (-)
    n_design_rpm: float = Field(..., ge=50_000, le=300_000)  # rev/min
    n_max_rpm: float = Field(..., ge=50_000, le=320_000)  # rev/min
    m_choke_max_kg_s: float = Field(..., gt=0.05, le=1.5)  # kg/s
    eta_max: float = Field(..., ge=0.60, le=0.82)  # (-)
    m_peak_kg_s: float = Field(..., gt=0.02, le=1.2)  # kg/s
    m_range_kg_s: float = Field(..., gt=0.02, le=1.0)  # kg/s
    k1: float = Field(0.6, ge=0.0, le=2.0)
    k2: float = Field(0.4, ge=0.0, le=2.0)
    n_peak_rpm: float = Field(..., ge=30_000, le=300_000)  # rev/min
    table: Grid2D | None = None  # mapa tabelado (x = pressure_ratio, y = rpm)


class TurboSpec(CatalogModel):
    housing: Literal["single_scroll", "twin_scroll"]
    compressor_ar: float | None = Field(None, gt=0.2, le=1.5)
    turbine_ar: float | None = Field(None, gt=0.2, le=1.5)
    rotor_inertia_kg_m2: float = Field(..., gt=1e-6, le=5e-4)  # kg·m²
    bearing_friction_k: float = Field(..., ge=0.0, le=1e-6)  # P_fric = k · ω², W·s²
    turbine_area_eff_cm2: float = Field(..., gt=1.0, le=40.0)  # cm²
    turbine_efficiency: Grid1D  # x = pressure_ratio
    wastegate_kind: Literal["internal", "external"]
    wastegate_area_max_cm2: float = Field(..., gt=0.5, le=20.0)  # cm²
    wastegate_spring_kpa: float = Field(..., ge=20.0, le=200.0)  # kPa relativa
    wastegate_full_open_delta_kpa: float = Field(40.0, gt=5.0, le=150.0)  # kPa
    blow_off_valve: bool = True
    compressor: CompressorMapSpec


class SuperchargerSpec(CatalogModel):
    sc_type: Literal["roots", "twin_screw"]
    displacement_l_per_rev: float = Field(..., gt=0.5, le=5.0)  # L/rev
    pulley_ratio: float = Field(..., ge=1.0, le=4.0)  # (-)
    k_leak: float = Field(0.08, ge=0.0, le=0.5)  # (-)
    n_ref_rpm: float = Field(10_000, ge=2_000, le=25_000)  # rev/min
    adiabatic_efficiency: Grid1D  # x = pressure_ratio
    mech_efficiency: float = Field(0.90, ge=0.70, le=0.98)  # (-)
    bypass_valve: bool = True
    max_rotor_rpm: float = Field(..., ge=5_000, le=30_000)  # rev/min


class InjectorSpec(CatalogModel):
    count_per_cyl: Literal[1, 2] = 1
    flow_cc_min: float = Field(..., gt=50.0, le=5000.0)  # cc/min a dp_ref_kpa
    dp_ref_kpa: float = Field(..., gt=100.0, le=40_000.0)  # kPa
    rail_pressure_min_kpa: float = Field(..., gt=100.0, le=40_000.0)  # kPa
    rail_pressure_max_kpa: float = Field(..., gt=100.0, le=40_000.0)  # kPa
    pressure_reference: Literal["manifold", "atmosphere", "cylinder"]  # GDI usa cylinder
    dead_time_ms: Grid2D  # x = battery_v, y = dp_kpa
    min_pulse_ms: float = Field(0.3, ge=0.0, le=3.0)  # ms
    max_duty_pct: float = Field(85.0, ge=50.0, le=100.0)  # %

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.rail_pressure_max_kpa < self.rail_pressure_min_kpa:
            raise ValueError("rail_pressure_max_kpa deve ser ≥ rail_pressure_min_kpa")
        return self


class FuelSpec(CatalogModel):
    fuel_id: FuelId
    display_name: str = Field(..., min_length=3, max_length=60)
    afr_stoich: float = Field(..., ge=8.0, le=15.5)  # (-)
    lhv_mj_kg: float = Field(..., ge=20.0, le=45.0)  # MJ/kg (PCI)
    ron: float = Field(..., ge=80.0, le=120.0)
    mon: float = Field(..., ge=70.0, le=110.0)
    knock_on: float = Field(..., ge=80.0, le=120.0)  # ON de Douaud-Eyzat
    h_fg_kj_kg: float = Field(..., ge=200.0, le=1200.0)  # kJ/kg
    density_kg_m3: float = Field(..., ge=650.0, le=850.0)  # kg/m³
    ethanol_mass_fraction: float = Field(..., ge=0.0, le=1.0)  # (-)
    laminar_bm_m_s: float  # m/s
    laminar_bphi_m_s: float  # m/s
    laminar_phi_m: float  # (-)
    preignition_surface_temp_c: float = Field(..., ge=600.0, le=1100.0)  # °C
    provenance: dict[str, Provenance] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def density_g_cc(self) -> float:
        """Densidade em g/cc (nome consumido pelo ecu-core)."""
        return self.density_kg_m3 / 1000.0


class MechanicalLimits(CatalogModel):
    """Limites mecânicos estruturais (D-21; consumidos pelo knock-and-failure-model)."""

    rod_torque_limit_nm: float = Field(..., gt=100.0, le=3000.0)  # N·m de freio sustentado
    max_rod_load_kn: float = Field(..., gt=10.0, le=300.0)  # kN de pico por biela
    max_cylinder_pressure_bar: float = Field(..., ge=60.0, le=250.0)  # bar abs
    egt_max_c: float = Field(..., ge=750.0, le=1100.0)  # °C pré-turbina
    max_rpm: float = Field(..., ge=4000.0, le=10_000.0)  # rev/min
    rev_limit_rpm: float = Field(..., ge=3000.0, le=10_000.0)  # rev/min, ≤ max_rpm
    valve_float_rpm: float = Field(..., ge=4000.0, le=11_000.0)  # rev/min, > max_rpm
    turbo_max_rpm: float | None = Field(None, ge=50_000, le=320_000)  # rev/min, só turbo
    max_piston_temp_c: float = Field(..., ge=250.0, le=450.0)  # °C coroa do pistão

    @computed_field  # type: ignore[prop-decorator]
    @property
    def egt_limit_c(self) -> float:
        """Sinônimo de ``egt_max_c`` usado pelo dyno-bench."""
        return self.egt_max_c

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.rev_limit_rpm <= self.max_rpm < self.valve_float_rpm:
            raise ValueError("exige rev_limit_rpm ≤ max_rpm < valve_float_rpm")
        return self


class RatedFigures(CatalogModel):
    peak_power_whp: float = Field(..., gt=50.0, le=1500.0)  # whp
    peak_power_rpm: float  # rev/min
    peak_torque_nm: float = Field(..., gt=50.0, le=2000.0)  # N·m na cambota
    peak_torque_rpm_from: float  # rev/min
    peak_torque_rpm_to: float  # rev/min
    power_ceiling_whp: float | None = None  # teto informativo do PRD
    power_range_whp: tuple[float, float] | None = None  # ex.: (300, 600)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.peak_torque_rpm_to < self.peak_torque_rpm_from:
            raise ValueError("peak_torque_rpm_to deve ser ≥ peak_torque_rpm_from")
        if self.power_range_whp is not None and self.power_range_whp[1] < self.power_range_whp[0]:
            raise ValueError("power_range_whp deve ser (mínimo, máximo)")
        return self


class ReferenceCommandPoint(CatalogModel):
    """Comando de malha aberta por RPM a plena carga (catalog RF-21)."""

    rpm: float = Field(gt=0.0)  # rev/min
    throttle_pct: float = Field(100.0, ge=0.0, le=100.0)  # %
    ignition_advance_deg: float = Field(..., ge=-30.0, le=60.0)  # ° BTDC
    lambda_target: float = Field(..., ge=0.65, le=1.10)  # (-)
    map_target_kpa: float = Field(..., ge=20.0, le=400.0)  # kPa abs
    wastegate_duty_pct: float = Field(0.0, ge=0.0, le=100.0)  # %
    vvt_intake_deg: float = 0.0  # °
    vvt_exhaust_deg: float = 0.0  # °
    injection_end_deg_btdc: float | None = None  # ° BTDC


class ReferenceCommandSchedule(CatalogModel):
    vehicle_id: VehicleId
    fuel_id: CatalogFuelId
    points: list[ReferenceCommandPoint] = Field(min_length=8, max_length=64)  # passo 250 rpm

    @model_validator(mode="after")
    def _check(self) -> Self:
        rpms = [p.rpm for p in self.points]
        steps = {round(b - a, 6) for a, b in itertools.pairwise(rpms)}
        if steps != {CURVE_RPM_STEP}:
            raise ValueError("points devem ter rpm crescente em passo de 250 rpm")
        return self


class FactoryCalibrationRef(CatalogModel):
    profile_id: ProfileIdLiteral
    calibration_id: str = Field(pattern=r"^stock-[0-9a-z-]+-(oem-stage|ft-pro|m1-race|ht-elite)$")
    file: str = Field(pattern=r"^calibrations/[0-9a-z-]+\.json$")
    sha256: Sha256Hex

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.calibration_id.endswith(f"-{self.profile_id}"):
            raise ValueError("calibration_id deve terminar no profile_id")
        if self.file != f"calibrations/{self.profile_id}.json":
            raise ValueError("file deve ser calibrations/<profile_id>.json")
        return self


class VehicleSpec(CatalogModel):
    vehicle_id: VehicleId
    display_name: str = Field(..., min_length=3, max_length=60)  # genérico, sem marcas
    architecture_note: str = Field(..., min_length=10, max_length=160)
    body: Literal["hatch", "sedan", "coupe"]
    data_version: int = Field(..., ge=1)
    validation_status: Literal["draft", "validated"]
    validated_on: date | None = None  # obrigatório se validated
    induction: Literal["turbo", "supercharger", "natural"]
    engine: EngineSpec
    turbo: TurboSpec | None = None
    supercharger: SuperchargerSpec | None = None
    injectors: InjectorSpec
    stock_fuel_id: CatalogFuelId
    allowed_fuel_ids: list[CatalogFuelId] = Field(min_length=1)
    drive_layout: Literal["fwd", "rwd", "awd"]
    gear_ratios: list[float] = Field(min_length=4, max_length=10)  # 1ª..n, decrescente
    final_drive_ratio: float = Field(..., ge=2.0, le=5.5)  # (-)
    tire_radius_m: float = Field(..., ge=0.25, le=0.40)  # m, raio dinâmico
    drivetrain_efficiency: float = Field(..., ge=0.70, le=0.95)  # η_drv
    drivetrain_fixed_loss_kw: float = Field(0.0, ge=0.0, le=20.0)  # kW
    driveline_inertia_kg_m2: float = Field(..., gt=0.5, le=10.0)  # kg·m² vista na roda
    mechanical_limits: MechanicalLimits
    rated: RatedFigures
    stock_profile_id: ProfileIdLiteral
    stock_calibration_id: str
    factory_calibrations: list[FactoryCalibrationRef] = Field(min_length=1)
    reference_command_schedule: ReferenceCommandSchedule
    reference_curve_ids: list[str] = Field(min_length=1)
    provenance: dict[str, Provenance] = Field(default_factory=dict)  # chave = ponteiro JSON

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        self._check_induction()
        self._check_fuel_and_calibrations()
        if self.validation_status == "validated" and self.validated_on is None:
            raise ValueError("validated_on é obrigatório em veículo validated")
        if not all(b < a for a, b in itertools.pairwise(self.gear_ratios)):
            raise ValueError("gear_ratios deve ser estritamente decrescente")
        if self.mechanical_limits.rod_torque_limit_nm <= self.rated.peak_torque_nm:
            raise ValueError("rod_torque_limit_nm deve ser maior que o torque de pico de série")
        if self.reference_command_schedule.vehicle_id != self.vehicle_id:
            raise ValueError("reference_command_schedule.vehicle_id difere de vehicle_id")
        if len(set(self.reference_curve_ids)) != len(self.reference_curve_ids):
            raise ValueError("reference_curve_ids com duplicados")
        return self

    def _check_induction(self) -> None:
        if self.induction == "turbo" and (self.turbo is None or self.supercharger is not None):
            raise ValueError("induction 'turbo' exige turbo e proíbe supercharger")
        if self.induction == "supercharger" and (
            self.supercharger is None or self.turbo is not None
        ):
            raise ValueError("induction 'supercharger' exige supercharger e proíbe turbo")
        if self.induction == "natural" and (self.turbo is not None or self.supercharger):
            raise ValueError("induction 'natural' proíbe turbo e supercharger")
        if self.engine.throttle_location == "pre_compressor" and self.induction != "supercharger":
            raise ValueError("throttle_location 'pre_compressor' só é aceite com supercharger")
        has_turbo_limit = self.mechanical_limits.turbo_max_rpm is not None
        if has_turbo_limit != (self.induction == "turbo"):
            raise ValueError("turbo_max_rpm é obrigatório se e só se induction = 'turbo'")

    def _check_fuel_and_calibrations(self) -> None:
        if self.stock_fuel_id not in self.allowed_fuel_ids:
            raise ValueError("stock_fuel_id deve estar em allowed_fuel_ids")
        if len(set(self.allowed_fuel_ids)) != len(self.allowed_fuel_ids):
            raise ValueError("allowed_fuel_ids com duplicados")
        expected = f"stock-{self.vehicle_id}-{self.stock_profile_id}"
        if self.stock_calibration_id != expected:
            raise ValueError(f"stock_calibration_id deve ser '{expected}'")
        profiles = [ref.profile_id for ref in self.factory_calibrations]
        if len(set(profiles)) != len(profiles):
            raise ValueError("factory_calibrations com perfil duplicado")
        for ref in self.factory_calibrations:
            if ref.calibration_id != f"stock-{self.vehicle_id}-{ref.profile_id}":
                raise ValueError(
                    f"factory_calibrations: calibration_id inválido para {ref.profile_id}"
                )
        if self.stock_profile_id not in profiles:
            raise ValueError("factory_calibrations deve incluir o stock_profile_id")

    def factory_calibration(self, profile_id: str) -> FactoryCalibrationRef | None:
        """Referência da calibração de fábrica do perfil, se existir."""
        return next((r for r in self.factory_calibrations if r.profile_id == profile_id), None)


# --------------------------------------------------------------------------- curvas


class ReferenceCurvePoint(CatalogModel):
    rpm: float = Field(..., ge=500.0, le=10_000.0)  # rev/min
    torque_crank_nm: float | None = Field(None, ge=0.0)  # N·m
    power_wheel_kw: float | None = Field(None, ge=0.0)  # kW
    lambda_value: float | None = Field(None, ge=0.6, le=1.3)  # (-)
    egt_c: float | None = Field(None, ge=200.0, le=1100.0)  # °C

    @computed_field  # type: ignore[prop-decorator]
    @property
    def power_wheel_whp(self) -> float | None:
        """Potência na roda em whp (1 hp = 0,7457 kW)."""
        return None if self.power_wheel_kw is None else self.power_wheel_kw / KW_PER_HP


class ReferenceConditions(CatalogModel):
    correction: Literal["sae_j1349", "din_70020", "uncorrected"] = "sae_j1349"
    ambient_temp_c: float = 25.0  # °C
    ambient_pressure_kpa: float = 99.0  # kPa
    dyno_type: Literal["inertial_roller", "loaded_roller", "engine_dyno"] = "inertial_roller"
    gear: int = Field(4, ge=1, le=10)


class ReferenceCurve(CatalogModel):
    """Curva do Reference Benchmark Baseline v1 (catalog RF-12)."""

    curve_id: str = Field(pattern=r"^[0-9a-z-]{3,64}$")  # ex.: "stock-e27"
    vehicle_id: VehicleId
    calibration_ref: str = Field("stock", min_length=1, max_length=64)  # "stock" ou calibration_id
    fuel_id: CatalogFuelId
    conditions: ReferenceConditions = Field(default_factory=ReferenceConditions)
    quantities: list[Quantity] = Field(min_length=1, max_length=4)
    points: list[ReferenceCurvePoint] = Field(min_length=8, max_length=64)
    source: str = Field(..., min_length=5, max_length=300)
    license: str = Field(..., min_length=2, max_length=64)  # SPDX ou "internal-estimate"
    confidence: Confidence
    quantity_confidence: dict[Quantity, Confidence] = Field(default_factory=dict)
    tolerance_pct: float = Field(5.0, gt=0.0, le=20.0)  # %
    benchmark_id: Literal["reference-benchmark-baseline-v1"] = BENCHMARK_ID

    @model_validator(mode="after")
    def _check(self) -> Self:
        rpms = [p.rpm for p in self.points]
        steps = {round(b - a, 6) for a, b in itertools.pairwise(rpms)}
        if steps != {CURVE_RPM_STEP}:
            raise ValueError("rpm deve ser estritamente crescente em passo de 250 rpm")
        if rpms[0] > CURVE_FIRST_RPM_MAX:
            raise ValueError("o primeiro ponto da curva deve ser ≤ 3000 rpm")
        if len(set(self.quantities)) != len(self.quantities):
            raise ValueError("quantities com duplicados")
        for quantity in self.quantities:
            if all(getattr(p, quantity) is None for p in self.points):
                raise ValueError(f"grandeza '{quantity}' sem nenhum valor nos pontos")
        return self

    def covers_rev_limit(self, rev_limit_rpm: float) -> bool:
        """RF-12: o último ponto deve ser ≥ ``rev_limit_rpm − 250``."""
        return self.points[-1].rpm >= rev_limit_rpm - CURVE_RPM_STEP


class QuantityDeviation(CatalogModel):
    quantity: Quantity
    max_deviation_pct: float = Field(ge=0.0)  # %
    rpm_at_max: float  # rev/min
    points_compared: int = Field(ge=0)


class ReferenceComparison(CatalogModel):
    curve_id: str
    deviations: list[QuantityDeviation]
    not_compared: list[Quantity]
    passed: bool


# --------------------------------------------------------------------------- respostas da API


class VehicleSummary(CatalogModel):
    vehicle_id: VehicleId
    display_name: str
    architecture_note: str
    body: str
    induction: str
    n_cyl: int = Field(ge=3, le=8)
    displacement_cc: float = Field(gt=0.0)  # cc
    stock_fuel_id: CatalogFuelId
    stock_profile_id: ProfileIdLiteral
    rated: RatedFigures
    validation_status: Literal["draft", "validated"]
    data_version: int = Field(ge=1)


class VehicleListResponse(CatalogModel):
    catalog_version: str
    catalog_sha256: Sha256Hex
    items: list[VehicleSummary]


class VehicleDetail(VehicleSpec):
    """``VehicleSpec`` + metadados do catálogo (E-04)."""

    estimated_fields: list[str]  # ponteiros JSON ordenados
    data_sha256: Sha256Hex
    catalog_version: str
    fuels: list[FuelSpec]  # os combustíveis de allowed_fuel_ids


class ReferenceCurveListResponse(CatalogModel):
    vehicle_id: VehicleId
    catalog_sha256: Sha256Hex
    benchmark_id: Literal["reference-benchmark-baseline-v1"] = BENCHMARK_ID
    benchmark_sha256: Sha256Hex  # hash dos arquivos de curva das 4 viaturas
    items: list[ReferenceCurve]
