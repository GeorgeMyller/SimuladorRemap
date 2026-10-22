"""Contratos dos perfis de ECU (ecu-profiles seção 9; simulation-bus 3.3).

- Descritor: ``EcuProfileDescriptor`` (``navigation``, ``live_tunable_table_ids``,
  ``load_axis_channel``) e as peças ``NavSection``/``TableSupport``/``StrategySupport``.
- Saídas por tick: ``ProfileStatus`` e ``ProfileEvent``.
- Base standalone: ``BaseSetup`` e sub-blocos, checklist, assistente, troca de ECU
  (``SwapRequest``/``SwapResult``), ``HardwareSheet``, ``VehicleEcuHardware`` e
  ``HardwareOverride`` (defeitos ocultos do training-scenarios, nunca expostos na API).

Os textos de validação usam o código estável da spec como mensagem
(ex.: ``FIRING_ORDER_INVALID``); o serviço mapeia para ``BASE_SETUP_INVALID``.
"""

from __future__ import annotations

import itertools
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from simremap.core.contracts import ContractModel, EntityId, Sha256Hex, SimStrEnum
from simremap.ecu.contracts import Axis, StrategyKind, TableKind

__all__ = [
    "BASE_SETUP_STEPS",
    "MINIMUM_CHECKLIST_IDS",
    "BaseSetup",
    "BaseSetupResult",
    "BaseSetupUpdate",
    "ChecklistItem",
    "DisplayUnits",
    "EcuProfileDescriptor",
    "EcuProfileId",
    "EcuProfileSummary",
    "EcuState",
    "FeaturePackage",
    "FuelSetup",
    "HardwareOverride",
    "HardwareSheet",
    "InjectorSetup",
    "MapSensorSetup",
    "NavItem",
    "NavSection",
    "NtcSensorSetup",
    "OemProtectionFlags",
    "OemSnapshot",
    "ProfileEvent",
    "ProfileFamily",
    "ProfileStatus",
    "ProtectionLimits",
    "SensorSetup",
    "SetupChecklist",
    "StrategySupport",
    "SwapRequest",
    "SwapResult",
    "TableSupport",
    "TriggerSetup",
    "TriggerWheel",
    "VehicleEcuHardware",
    "WidebandSetup",
    "WizardInputs",
]


class EcuProfileId(SimStrEnum):
    OEM_STAGE = "oem-stage"
    FT_PRO = "ft-pro"
    M1_RACE = "m1-race"
    HT_ELITE = "ht-elite"


class ProfileFamily(SimStrEnum):
    OEM = "oem"
    STANDALONE = "standalone"


EcuState = Literal["oem", "awaiting_base_setup", "standalone_ready"]
FeaturePackage = Literal["base", "race"]
TriggerWheel = Literal["60-2", "36-1", "36-2", "24-1", "12-1", "4-0"]
FuelIdLiteral = Literal["e0", "e27", "e100", "podium"]
NtcCurve = Literal["ntc_a", "ntc_b", "ntc_c"]
FuelModelMode = Literal["speed_density_ve", "direct_pulse_ms", "profile_air_model"]
BaseSetupStep = Literal["trigger", "injectors", "fuel", "sensors", "protection", "review"]
BASE_SETUP_STEPS: Final[tuple[str, ...]] = (
    "trigger",
    "injectors",
    "fuel",
    "sensors",
    "protection",
    "review",
)
SEMVER_PATTERN: Final = r"^\d+\.\d+\.\d+$"
Cylinder = Annotated[int, Field(ge=1, le=12)]


def _base_package_only() -> list[FeaturePackage]:
    return ["base"]


def _is_permutation(order: list[int]) -> bool:
    return sorted(order) == list(range(1, len(order) + 1))


def _strictly_increasing(values: list[float]) -> bool:
    return all(b > a for a, b in itertools.pairwise(values))


# --------------------------------------------------------------------------- descritor


class NavItem(ContractModel):
    id: str = Field(pattern=r"^[a-z][-_0-9a-z.]{1,63}$")
    label: str = Field(min_length=1, max_length=60)  # nome genérico, sem marcas
    kind: Literal["table", "strategy", "base_setup", "info"]
    target_id: str = Field(min_length=1, max_length=64)  # table_id, kind ou passo do assistente
    cylinder: Cylinder | None = None  # itens por cilindro (trims)
    requires_package: Literal["race"] | None = None  # só m1-race


class NavSection(ContractModel):
    id: str = Field(pattern=r"^[a-z][-_0-9a-z]{1,47}$")
    label: str = Field(min_length=1, max_length=60)
    items: list[NavItem] = Field(min_length=1)


class TableSupport(ContractModel):
    kind: TableKind
    required: bool  # obrigatória na calibração do perfil
    default_x: Axis
    default_y: Axis | None = None  # None para Table2D
    display_name: str = Field(max_length=60)  # terminologia do perfil
    per_cylinder: bool = False
    live_tunable: bool  # sobrepõe o padrão do ecu-core


class StrategySupport(ContractModel):
    kind: StrategyKind
    level: Literal["supported", "package_race", "unsupported"]
    restricted_options: dict[str, list[str]] = Field(default_factory=dict)
    display_name: str = Field(max_length=60)


class DisplayUnits(ContractModel):
    pressure: Literal["kpa_abs", "bar_rel", "psi_rel"] = "kpa_abs"
    mixture: Literal["lambda", "afr"] = "lambda"
    injection: Literal["ms", "ve_pct", "fuel_mass_mg"] = "ve_pct"
    temperature: Literal["c"] = "c"
    torque: Literal["nm"] = "nm"
    power: Literal["whp", "cv", "kw"] = "whp"


class EcuProfileSummary(ContractModel):
    """Item de ``GET /api/v1/ecu-profiles`` (E-21)."""

    profile_id: EcuProfileId
    name: str = Field(min_length=1, max_length=60)  # nome genérico ("OEM-Stage")
    family: ProfileFamily
    inspiration: str = Field(max_length=200)  # texto genérico, sem marcas
    descriptor_version: str = Field(pattern=SEMVER_PATTERN)


class EcuProfileDescriptor(EcuProfileSummary):
    """Descritor completo de um perfil (E-22; profiles RF-03, RF-28)."""

    fuel_model_modes: list[FuelModelMode] = Field(min_length=1)
    default_fuel_model_mode: FuelModelMode
    tables: list[TableSupport] = Field(min_length=1)
    strategies: list[StrategySupport]  # sempre as 10 kinds do ecu-core
    terminology: dict[str, str]  # chave canônica → rótulo exibido
    display_units: DisplayUnits
    requires_base_setup: bool  # False no oem-stage
    base_setup_steps: list[BaseSetupStep]
    feature_packages: list[FeaturePackage] = Field(default_factory=_base_package_only)
    navigation: list[NavSection] = Field(min_length=1)
    live_tunable_table_ids: list[str] = Field(default_factory=list)
    load_axis_channel: Literal["map_kpa", "load_pct", "torque_request_nm", "throttle_pct"]
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")  # acento neutro

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.default_fuel_model_mode not in self.fuel_model_modes:
            raise ValueError("default_fuel_model_mode deve estar em fuel_model_modes")
        kinds = [s.kind for s in self.strategies]
        if sorted(kinds) != sorted(StrategyKind):
            raise ValueError("strategies deve listar exatamente as 10 kinds do ecu-core")
        table_kinds = [t.kind for t in self.tables]
        if len(set(table_kinds)) != len(table_kinds):
            raise ValueError("tables com kind duplicado")
        live_kinds = {t.kind.value for t in self.tables if t.live_tunable}
        unknown_live = set(self.live_tunable_table_ids) - live_kinds
        if unknown_live:
            raise ValueError(
                f"live_tunable_table_ids sem tabela live_tunable: {sorted(unknown_live)}"
            )
        if self.requires_base_setup == (self.family == ProfileFamily.OEM):
            raise ValueError("requires_base_setup deve ser False só na família oem")
        if self.requires_base_setup and not self.base_setup_steps:
            raise ValueError("perfil standalone exige base_setup_steps")
        if "base" not in self.feature_packages:
            raise ValueError("feature_packages deve incluir 'base'")
        nav_ids = [item.id for section in self.navigation for item in section.items]
        if len(set(nav_ids)) != len(nav_ids):
            raise ValueError("navigation com item id duplicado")
        return self


# --------------------------------------------------------------------------- BaseSetup


class TriggerSetup(ContractModel):
    wheel: TriggerWheel
    tdc_offset_deg: float = Field(ge=0.0, lt=360.0)  # ° de cambota da falha ao PMS do cil. 1
    phase_sensor: Literal["none", "cam_hall"] = "none"
    phase_edge_deg: float = Field(default=0.0, ge=0.0, lt=720.0)  # °
    injection_mode: Literal["sequential", "semi_sequential", "batch"] = "semi_sequential"
    ignition_mode: Literal["sequential", "wasted_spark"] = "wasted_spark"
    firing_order: list[int] = Field(min_length=3, max_length=8)  # ex.: [1, 3, 4, 2]
    timing_lock_deg: float | None = Field(default=None, ge=-5.0, le=30.0)  # ° BTDC; None = livre

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not _is_permutation(self.firing_order):
            raise ValueError("FIRING_ORDER_INVALID")
        if (
            "sequential" in (self.injection_mode, self.ignition_mode)
            and self.phase_sensor == "none"
        ):
            raise ValueError("SEQUENTIAL_REQUIRES_PHASE_SENSOR")
        return self


class InjectorSetup(ContractModel):
    flow_cc_min: float = Field(gt=0.0, le=5000.0)  # cc/min a ref_pressure_kpa
    ref_pressure_kpa: float = Field(default=300.0, ge=200.0, le=600.0)  # kPa
    dead_time_v: list[float] = Field(
        default_factory=lambda: [8.0, 10.0, 12.0, 13.5, 14.5, 16.0], min_length=2, max_length=16
    )  # V
    dead_time_ms: list[float] = Field(min_length=2, max_length=16)  # ms, 0..5
    fuel_pressure_mode: Literal["fixed_rail", "map_referenced"] = "map_referenced"
    rail_pressure_kpa: float = Field(default=300.0, ge=200.0, le=800.0)  # kPa
    # Modelo físico do bico (m1-race): vazão vs ΔP e adição de pulso curto
    flow_vs_dp_kpa: list[float] | None = None  # kPa
    flow_vs_dp_factor: list[Annotated[float, Field(ge=0.3, le=1.8)]] | None = None  # (-)
    short_pulse_ms: list[float] | None = None  # ms
    short_pulse_adder_ms: list[Annotated[float, Field(ge=-0.3, le=0.3)]] | None = None  # ms

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.dead_time_ms) != len(self.dead_time_v):
            raise ValueError("DEAD_TIME_SHAPE_MISMATCH")
        if not _strictly_increasing(self.dead_time_v):
            raise ValueError("TABLE_AXIS_NOT_MONOTONIC")
        if any(not 0.0 <= v <= 5.0 for v in self.dead_time_ms):  # noqa: PLR2004
            raise ValueError("DEAD_TIME_OUT_OF_RANGE")
        for x_name, y_name in (
            ("flow_vs_dp_kpa", "flow_vs_dp_factor"),
            ("short_pulse_ms", "short_pulse_adder_ms"),
        ):
            xs, ys = getattr(self, x_name), getattr(self, y_name)
            if (xs is None) != (ys is None):
                raise ValueError(f"{x_name} e {y_name} vêm juntos")
            if xs is not None:
                if len(xs) != len(ys) or len(xs) < 2:  # noqa: PLR2004
                    raise ValueError(f"{x_name} e {y_name} com formas diferentes")
                if not _strictly_increasing(xs):
                    raise ValueError("TABLE_AXIS_NOT_MONOTONIC")
        return self


class FuelSetup(ContractModel):
    fuel_id: FuelIdLiteral  # ids do vehicle-catalog
    afr_stoich: float = Field(ge=8.0, le=15.5)  # (-), editável para erro didático
    density_g_cc: float = Field(ge=0.68, le=0.82)  # g/cc


class MapSensorSetup(ContractModel):
    min_kpa: float = Field(ge=0.0, le=50.0)  # kPa a 0,5 V
    max_kpa: float = Field(ge=100.0, le=700.0)  # kPa a 4,5 V


class NtcSensorSetup(ContractModel):
    curve: NtcCurve = "ntc_a"  # curvas genéricas (Apêndice D)


class WidebandSetup(ContractModel):
    lambda_at_0v: float = Field(default=0.5, ge=0.4, le=1.0)  # (-)
    lambda_at_5v: float = Field(default=1.5, ge=1.0, le=2.5)  # (-)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.lambda_at_5v <= self.lambda_at_0v:
            raise ValueError("lambda_at_5v deve ser maior que lambda_at_0v")
        return self


class SensorSetup(ContractModel):
    map: MapSensorSetup | None = None
    iat: NtcSensorSetup = Field(default_factory=NtcSensorSetup)
    ect: NtcSensorSetup = Field(default_factory=NtcSensorSetup)
    wideband: WidebandSetup | None = None  # None = malha fechada indisponível


class ProtectionLimits(ContractModel):
    rev_limit_rpm: float = Field(default=7000.0, ge=2000.0, le=12000.0)  # rev/min
    overspeed_rpm: float = Field(default=7500.0, ge=2000.0, le=13000.0)  # rev/min
    overboost_kpa: float = Field(default=260.0, ge=100.0, le=500.0)  # kPa abs
    egt_max_c: float = Field(default=950.0, ge=600.0, le=1100.0)  # °C
    ect_max_c: float = Field(default=110.0, ge=80.0, le=130.0)  # °C
    oil_pressure_min_kpa: float = Field(default=100.0, ge=0.0, le=600.0)  # kPa
    lean_delta_lambda: float = Field(default=0.10, ge=0.03, le=0.30)  # Δλ

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.overspeed_rpm <= self.rev_limit_rpm:
            raise ValueError("OVERSPEED_BELOW_REV_LIMIT")
        return self


class BaseSetup(ContractModel):
    trigger: TriggerSetup | None = None
    injectors: InjectorSetup | None = None
    fuel: FuelSetup | None = None
    sensors: SensorSetup = Field(default_factory=SensorSetup)
    protection: ProtectionLimits = Field(default_factory=ProtectionLimits)
    feature_package: FeaturePackage = "base"  # só relevante no m1-race


ChecklistItemId = Literal[
    "trigger.wheel",
    "trigger.tdc_offset",
    "trigger.phase",
    "trigger.firing_order",
    "injectors.flow",
    "injectors.dead_time",
    "fuel.type",
    "sensors.map",
    "sensors.iat",
    "sensors.ect",
    "sensors.wideband",
    "protection.limits",
    "base_map",
]
MINIMUM_CHECKLIST_IDS: Final[frozenset[str]] = frozenset(
    {"trigger.wheel", "injectors.flow", "injectors.dead_time", "fuel.type", "sensors.map"}
)


class ChecklistItem(ContractModel):
    id: ChecklistItemId
    required: bool
    status: Literal["ok", "missing", "invalid", "warning"]
    code: str | None = Field(None, max_length=64)  # ex.: "FUEL_MISMATCH_SUSPECTED"
    message: str = Field("", max_length=300)  # pt-BR, genérico


class SetupChecklist(ContractModel):
    items: list[ChecklistItem]
    minimum_valid: bool  # itens mínimos em ok ou warning

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [item.id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("checklist com item duplicado")
        status: dict[str, str] = {item.id: item.status for item in self.items}
        computed = all(status.get(i) in ("ok", "warning") for i in MINIMUM_CHECKLIST_IDS)
        if self.minimum_valid != computed:
            raise ValueError("minimum_valid incoerente com os itens mínimos")
        return self

    @classmethod
    def from_items(cls, items: list[ChecklistItem]) -> SetupChecklist:
        """Monta a checklist calculando ``minimum_valid``."""
        status: dict[str, str] = {item.id: item.status for item in items}
        minimum = all(status.get(i) in ("ok", "warning") for i in MINIMUM_CHECKLIST_IDS)
        return cls(items=items, minimum_valid=minimum)


class WizardInputs(ContractModel):
    max_map_kpa: float = Field(default=200.0, ge=100.0, le=450.0)  # kPa abs
    rev_limit_rpm: float | None = Field(default=None, ge=2000.0, le=12000.0)  # None = protection
    idle_rpm: float = Field(default=900.0, ge=600.0, le=1500.0)  # rev/min
    grid: Literal[12, 16, 20] = 16
    fuel_model_mode: Literal["speed_density_ve", "direct_pulse_ms"] | None = None


class OemSnapshot(ContractModel):
    calibration_id: EntityId
    version: int = Field(ge=1)
    content_hash: Sha256Hex


class HardwareSheet(ContractModel):
    """O que um mecânico vê no carro; nunca contém o PMS real."""

    trigger_wheel: TriggerWheel
    phase_sensor_present: bool
    firing_order: list[int] = Field(min_length=3, max_length=8)
    injector_label_cc_min: float = Field(gt=0.0)  # cc/min
    tank_fuel_id: FuelIdLiteral
    map_sensor_label_kpa: tuple[float, float]  # kPa (mín, máx)
    tdc_offset_nominal_deg: float = Field(ge=0.0, lt=360.0)  # °
    n_cyl: int = Field(ge=3, le=8)
    displacement_cc: float = Field(gt=0.0)  # cc

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.firing_order) != self.n_cyl or not _is_permutation(self.firing_order):
            raise ValueError("firing_order deve ser permutação de 1..n_cyl")
        return self


class SwapRequest(ContractModel):
    """Pedido de ``POST .../ecu/swap`` (E-23)."""

    target_profile_id: EcuProfileId
    confirm_snapshot: bool  # deve ser True ao sair do oem-stage
    feature_package: FeaturePackage = "base"
    prefill_from_hardware_sheet: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=64)  # idempotência


class SwapResult(ContractModel):
    session_id: EntityId
    previous_profile_id: EcuProfileId
    profile_id: EcuProfileId
    ecu_state: EcuState
    oem_snapshot: OemSnapshot | None
    base_setup_version: int | None = Field(ge=1)
    calibration_id: EntityId | None
    checklist: SetupChecklist
    hardware_sheet: HardwareSheet


class BaseSetupUpdate(ContractModel):
    """Pedido de ``PUT .../ecu/base-setup`` (E-25)."""

    base_version: int | None = Field(default=None, ge=1)  # None só na primeira gravação
    base_setup: BaseSetup
    generate_base_map: bool = False
    wizard: WizardInputs | None = None
    apply_limits_to_calibration: bool = True


class BaseSetupResult(ContractModel):
    session_id: EntityId
    profile_id: EcuProfileId
    editable: bool
    ecu_state: EcuState
    base_setup_version: int | None = Field(ge=1)
    base_setup: BaseSetup | None
    setup_hash: Sha256Hex | None  # SHA-256 do JSON canônico da base
    checklist: SetupChecklist
    hardware_sheet: HardwareSheet
    calibration_id: EntityId | None = None
    calibration_version: int | None = Field(None, ge=1)
    estimated_peak_duty_pct: float | None = Field(None, ge=0.0)  # %
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- hardware


class VehicleEcuHardware(ContractModel):
    """Verdade física por veículo (``data/hardware/<vehicle_id>.json``)."""

    vehicle_id: EntityId
    trigger_wheel: TriggerWheel
    tdc_offset_true_deg: float = Field(ge=0.0, lt=360.0)  # °
    tdc_offset_nominal_deg: float = Field(ge=0.0, lt=360.0)  # °
    phase_sensor_present: bool
    phase_edge_true_deg: float = Field(ge=0.0, lt=720.0)  # °
    firing_order: list[int] = Field(min_length=3, max_length=8)
    map_sensor_kpa: tuple[float, float]  # kPa (mín, máx)
    iat_curve: NtcCurve = "ntc_a"
    ect_curve: NtcCurve = "ntc_a"
    wideband_true: tuple[float, float] = (0.5, 1.5)  # λ a 0 V e a 5 V
    swap_supported: bool = True

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not _is_permutation(self.firing_order):
            raise ValueError("FIRING_ORDER_INVALID")
        if self.map_sensor_kpa[1] <= self.map_sensor_kpa[0]:
            raise ValueError("map_sensor_kpa deve ser (mín, máx)")
        return self


class HardwareOverride(ContractModel):
    """Defeito oculto de hardware vindo do training-scenarios (nunca exposto na API)."""

    tdc_offset_shift_deg: float = Field(default=0.0, ge=-40.0, le=40.0)  # °
    trigger_wheel: TriggerWheel | None = None
    injector_flow_cc_min: float | None = Field(default=None, gt=0.0)  # cc/min
    map_sensor_kpa: tuple[float, float] | None = None  # kPa (mín, máx)
    tank_fuel_id: FuelIdLiteral | None = None


class OemProtectionFlags(ContractModel):
    """Flags OEM guardadas em ``Calibration.profile_params``."""

    torque_monitoring: bool = True
    component_protection: bool = True
    knock_protection: bool = True
    overboost_protection: bool = True
    checksum_check: bool = True


# --------------------------------------------------------------------------- saídas por tick


class ProfileStatus(ContractModel):
    """Snapshot decimado do adaptador de perfil (no laço: dataclass com slots)."""

    t_sim_s: float = Field(ge=0.0)  # s
    profile_id: EcuProfileId
    ecu_state: EcuState
    sync_ok: bool
    ign_cmd_deg: list[float] = Field(min_length=1, max_length=8)  # ° BTDC comandado por cilindro
    ign_real_minus_cmd_deg: float  # °
    timing_light_deg: float | None  # ° lido com a pistola de ponto
    map_read_kpa: float  # kPa lido pela ECU
    lambda_read: float | None  # (-)
    # Caminho de torque (só oem-stage; None nos outros perfis)
    oem_torque_request_nm: float | None = None  # N·m
    oem_torque_desired_ind_nm: float | None = None  # N·m
    oem_torque_limiter_active: (
        Literal["none", "torque_limit", "gear", "limp", "protection"] | None
    ) = None
    oem_load_target_pct: float | None = None  # %
    oem_load_actual_pct: float | None = None  # %
    oem_pressure_target_kpa: float | None = None  # kPa
    oem_torque_ign_retard_deg: float | None = None  # °
    oem_limp_mode: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.profile_id != EcuProfileId.OEM_STAGE:
            oem_fields = [
                name
                for name in type(self).model_fields
                if name.startswith("oem_") and getattr(self, name) is not None
            ]
            if oem_fields:
                raise ValueError(f"campos oem_* só no oem-stage: {oem_fields}")
        return self


class ProfileEvent(ContractModel):
    t_sim_s: float = Field(ge=0.0)  # s
    kind: Literal[
        "trigger_sync_lost",
        "trigger_sync_ok",
        "tdc_offset_out_of_range",
        "firing_order_misfire",
        "no_start_setup_incomplete",
        "oem_limp_mode",
        "oem_protection_disabled",
        "oem_checksum_corrected",
        "fuel_mismatch_suspected",
        "injector_undersized",
    ]
    cylinder: Cylinder | None = None
    value: float | None = None
    detail: str = Field("", max_length=200)
