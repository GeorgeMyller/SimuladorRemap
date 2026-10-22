"""Contratos do modelo de knock e falhas (knock-and-failure-model seção 9; simulation-bus 4.6).

Modelos imutáveis que recusam campos extra. Listas por cilindro têm comprimento ``n_cyl``,
índice 0 = cilindro 1. Temperaturas na API em °C. ``KnockSignal`` pertence ao
engine-physics-core (D-14) e é reexportado daqui por conveniência.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from simremap.catalog.contracts import FuelId, VehicleId
from simremap.core.contracts import ContractModel, Sha256Hex, SimStrEnum
from simremap.physics.contracts import MAX_CYLINDERS, KnockSignal

__all__ = [
    "COMPONENT_ID_PATTERN",
    "DAMAGE_CAUSES",
    "INTACT_THRESHOLD",
    "MAX_CAUSAL_LINKS",
    "Audience",
    "CalibrationDiff",
    "CausalLink",
    "ChannelStats",
    "ComponentHealth",
    "ComponentKind",
    "DamageState",
    "EarlyWarning",
    "EngineHealth",
    "EngineRestoreRequest",
    "FailureEvent",
    "FailureMechanism",
    "FailureMode",
    "ForensicReport",
    "Health",
    "KnockClass",
    "KnockObservation",
    "KnockSignal",
    "LwTracePoint",
    "NarrativeText",
    "Recommendation",
    "ReportKind",
    "TableDelta",
    "TimeWindow",
    "classify_knock",
    "integrity_pct",
]

COMPONENT_ID_PATTERN: Final = (
    r"^(piston|rod|valves):[1-8]$|^head_gasket$|^bearings$|^turbo:turbine$"
)
_COMPONENT_ID_RE: Final = re.compile(COMPONENT_ID_PATTERN)
ULID_PATTERN: Final = r"^[0-9A-HJKMNP-TV-Z]{26}$"
SEMVER_PATTERN: Final = r"^\d+\.\d+\.\d+$"
INTACT_THRESHOLD: Final = 0.999
MAX_CAUSAL_LINKS: Final = 12
DAMAGE_CAUSES: Final[frozenset[str]] = frozenset(
    {"knock", "thermal", "overload", "overrev", "preignition", "pressure"}
)
# Limiares de classe de knock por intensidade (bar de MAPO).
KNOCK_LIGHT_MIN: Final = 0.3
KNOCK_MODERATE_MIN: Final = 1.0
KNOCK_SEVERE_MIN: Final = 3.0

Health = Annotated[float, Field(ge=0.0, le=1.0)]
Ulid = Annotated[str, Field(pattern=ULID_PATTERN)]
Cylinder = Annotated[int, Field(ge=1, le=MAX_CYLINDERS)]


class FailureMode(SimStrEnum):
    KNOCK_DAMAGE = "knock_damage"
    PRE_IGNITION = "pre_ignition"
    EGT_OVERTEMP = "egt_overtemp"
    ROD_FAILURE = "rod_failure"
    PISTON_FAILURE = "piston_failure"
    TURBO_MELTDOWN = "turbo_meltdown"


class FailureMechanism(SimStrEnum):
    KNOCK_EROSION = "knock_erosion"  # furo/erosão da coroa por knock
    RING_LAND_CRACK = "ring_land_crack"  # aviso de knock_damage
    HEAD_GASKET_BREACH = "head_gasket_breach"
    PISTON_THERMAL_MELT = "piston_thermal_melt"
    VALVE_PISTON_CONTACT = "valve_piston_contact"
    EXHAUST_VALVE_BURN = "exhaust_valve_burn"
    ROD_OVERLOAD = "rod_overload"
    ROD_INSTANT_BEND = "rod_instant_bend"
    BEARING_SPIN = "bearing_spin"
    HOT_SPOT_PREIGNITION = "hot_spot_preignition"
    LSPI = "lspi"
    TURBINE_CREEP = "turbine_creep"
    TURBO_OVERSPEED_BURST = "turbo_overspeed_burst"


class KnockClass(SimStrEnum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    SEVERE = "severe"


ComponentKind = Literal["piston", "rod", "valves", "head_gasket", "bearings", "turbine"]
Audience = Literal["beginner", "intermediate", "instructor"]
ReportKind = Literal["failure", "near_miss"]

_KIND_BY_PREFIX: Final[dict[str, ComponentKind]] = {
    "piston": "piston",
    "rod": "rod",
    "valves": "valves",
    "head_gasket": "head_gasket",
    "bearings": "bearings",
    "turbo": "turbine",
}


def classify_knock(intensity_bar: float) -> KnockClass:
    """Classe de knock: ``none`` < 0,3 ≤ ``light`` < 1,0 ≤ ``moderate`` < 3,0 ≤ ``severe``."""
    if intensity_bar >= KNOCK_SEVERE_MIN:
        return KnockClass.SEVERE
    if intensity_bar >= KNOCK_MODERATE_MIN:
        return KnockClass.MODERATE
    if intensity_bar >= KNOCK_LIGHT_MIN:
        return KnockClass.LIGHT
    return KnockClass.NONE


def integrity_pct(min_health: float) -> float:
    """``floor(1000 · min_health) / 10`` (0..100 %)."""
    return int(1000 * min_health) / 10


def _component_cylinder(component_id: str) -> int | None:
    prefix, _, suffix = component_id.partition(":")
    if prefix in ("piston", "rod", "valves"):
        return int(suffix)
    return None


def _check_component_id(component_id: str, cylinder: int | None) -> ComponentKind:
    if _COMPONENT_ID_RE.fullmatch(component_id) is None:
        raise ValueError(f"component_id inválido: {component_id!r}")
    expected = _component_cylinder(component_id)
    if expected is not None and cylinder is not None and cylinder != expected:
        raise ValueError(f"cylinder {cylinder} difere do component_id {component_id!r}")
    return _KIND_BY_PREFIX[component_id.partition(":")[0]]


# --------------------------------------------------------------------------- barramento


class ComponentHealth(ContractModel):
    component_id: str = Field(pattern=COMPONENT_ID_PATTERN)
    kind: ComponentKind
    cylinder: Cylinder | None = None
    health: Health = 1.0  # 0..1 (1 = intacto)
    virtual_health: Health = 1.0  # 0..1, modo dano desligado (RF-29)
    damage_by_cause: dict[str, Annotated[float, Field(ge=0.0)]] = Field(default_factory=dict)
    failed: bool = False
    first_damage_t_sim_s: float | None = Field(None, ge=0.0)  # s

    @model_validator(mode="after")
    def _check(self) -> Self:
        kind = _check_component_id(self.component_id, self.cylinder)
        if kind != self.kind:
            raise ValueError(f"kind '{self.kind}' difere do component_id {self.component_id!r}")
        if _component_cylinder(self.component_id) != self.cylinder:
            raise ValueError("cylinder deve acompanhar o component_id (None nos globais)")
        unknown = set(self.damage_by_cause) - DAMAGE_CAUSES
        if unknown:
            raise ValueError(f"causas de dano desconhecidas: {sorted(unknown)}")
        return self


class KnockObservation(ContractModel):
    cylinder: Cylinder
    t_sim_s: float = Field(ge=0.0)  # s
    rpm: float = Field(ge=0.0)  # rev/min
    lw_integral_end: float = Field(ge=0.0)  # I_LW no fim da combustão (-)
    theta_onset_deg_atdc: float | None  # θ_k em ° ATDC; None sem knock
    burned_fraction_onset: float | None = Field(None, ge=0.0, le=1.0)  # (-)
    autoignited_fraction: float = Field(ge=0.0, le=1.0)  # (-)
    mapo_kpa: float = Field(ge=0.0)  # kPa
    intensity: float = Field(ge=0.0)  # bar de MAPO
    knock_energy_j: float = Field(ge=0.0)  # J
    knock_class: KnockClass
    in_sensor_window: bool
    preignition: Literal["none", "hot_spot", "lspi"] = "none"
    p_preignition_kpa: float | None = Field(None, ge=0.0)  # kPa

    @model_validator(mode="after")
    def _check(self) -> Self:
        if classify_knock(self.intensity) != self.knock_class:
            raise ValueError("knock_class incoerente com intensity")
        return self


class FailureEvent(ContractModel):
    failure_event_id: Ulid
    session_id: str = Field(min_length=1, max_length=36)
    run_id: Ulid | None  # None fora de puxada
    tick: int = Field(ge=0)
    t_sim_s: float = Field(ge=0.0)  # s
    cylinder: Cylinder | None = None
    component_id: str = Field(pattern=COMPONENT_ID_PATTERN, max_length=16)
    mode: FailureMode
    mechanism: FailureMechanism
    catastrophic: bool
    simulated_only: bool = False  # dano desligado
    health_after: Health
    causal_variables: dict[str, float]  # knock_intensity, piston_temp_eff_c, torque_nm, ...

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_component_id(self.component_id, self.cylinder)
        return self


class DamageState(ContractModel):
    """Saída do ``DamageModel.step`` (simulation-bus 4.6)."""

    t_sim_s: float = Field(ge=0.0)  # s
    tick: int = Field(ge=0)
    damage_enabled: bool
    engine_locked: bool
    components: list[ComponentHealth]
    knock_last: list[KnockObservation | None]  # por cilindro, último ciclo
    knock_signal: KnockSignal
    piston_temp_eff_c: list[float]  # °C por cilindro
    new_failures: list[FailureEvent] = Field(default_factory=list)  # eventos do tick
    damage_digest: Sha256Hex | None = None  # só no fim de puxada

    @model_validator(mode="after")
    def _check(self) -> Self:
        n_cyl = len(self.piston_temp_eff_c)
        if not 1 <= n_cyl <= MAX_CYLINDERS:
            raise ValueError("piston_temp_eff_c deve ter 1..8 cilindros")
        if len(self.knock_last) != n_cyl or len(self.knock_signal.intensity) != n_cyl:
            raise ValueError("knock_last e knock_signal devem ter n_cyl itens")
        for index, observation in enumerate(self.knock_last, start=1):
            if observation is not None and observation.cylinder != index:
                raise ValueError(f"knock_last[{index - 1}] deve ser do cilindro {index}")
        ids = [c.component_id for c in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError("components com component_id duplicado")
        return self


# --------------------------------------------------------------------------- API


class EngineHealth(ContractModel):
    """Resposta de ``GET .../engine/health`` e ``POST .../engine/restore`` (E-12, E-13)."""

    session_id: str = Field(min_length=1, max_length=36)
    vehicle_id: VehicleId
    t_sim_s: float = Field(ge=0.0)  # s
    damage_enabled: bool
    engine_locked: bool
    components: list[ComponentHealth] = Field(min_length=1)
    min_health: Health
    integrity_pct: float = Field(ge=0.0, le=100.0)  # floor(1000 · min_health) / 10
    intact: bool  # min_health ≥ 0,999
    failures: list[FailureEvent] = Field(default_factory=list)
    restore_count: int = Field(0, ge=0)
    last_forensic_report_url: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if abs(self.min_health - min(c.health for c in self.components)) > 1e-12:  # noqa: PLR2004
            raise ValueError("min_health deve ser a menor saúde dos componentes")
        if abs(self.integrity_pct - integrity_pct(self.min_health)) > 1e-9:  # noqa: PLR2004
            raise ValueError("integrity_pct deve ser floor(1000 · min_health) / 10")
        if self.intact != (self.min_health >= INTACT_THRESHOLD):
            raise ValueError("intact deve ser min_health ≥ 0,999")
        return self

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        vehicle_id: str,
        t_sim_s: float,
        damage_enabled: bool,
        engine_locked: bool,
        components: list[ComponentHealth],
        failures: list[FailureEvent] | None = None,
        restore_count: int = 0,
        last_forensic_report_url: str | None = None,
    ) -> EngineHealth:
        """Monta a resposta calculando ``min_health``, ``integrity_pct`` e ``intact``."""
        min_health = min(c.health for c in components)
        return cls(
            session_id=session_id,
            vehicle_id=vehicle_id,
            t_sim_s=t_sim_s,
            damage_enabled=damage_enabled,
            engine_locked=engine_locked,
            components=components,
            min_health=min_health,
            integrity_pct=integrity_pct(min_health),
            intact=min_health >= INTACT_THRESHOLD,
            failures=failures or [],
            restore_count=restore_count,
            last_forensic_report_url=last_forensic_report_url,
        )


class EngineRestoreRequest(ContractModel):
    note: str | None = Field(None, max_length=120)  # texto técnico livre, sem PII


class CausalLink(ContractModel):
    order: int = Field(ge=1)
    t_sim_s: float = Field(ge=0.0)  # s
    kind: Literal[
        "calibration",
        "operating_point",
        "combustion",
        "ecu_response",
        "damage",
        "warning",
        "failure",
    ]
    cylinder: Cylinder | None = None
    variable: str = Field(min_length=1, max_length=64)  # nome de canal ou de campo
    value: float
    threshold: float | None = None
    unit: str = Field(max_length=16)
    description: str = Field(max_length=240)


class ChannelStats(ContractModel):
    min: float
    max: float
    mean: float
    unit: str = Field(max_length=16)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.min <= self.mean <= self.max:
            raise ValueError("exige min ≤ mean ≤ max")
        return self


class TimeWindow(ContractModel):
    name: Literal[
        "before", "warning", "collapse"
    ]  # (t_f−10, t_f−3), (t_f−3, t_f−0,5), (t_f−0,5, t_f)
    t_start_s: float  # s
    t_end_s: float  # s
    stats: dict[str, ChannelStats]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.t_end_s < self.t_start_s:
            raise ValueError("t_end_s deve ser ≥ t_start_s")
        return self


class EarlyWarning(ContractModel):
    signal: Literal[
        "knock_retard_rising",
        "first_moderate_knock",
        "knock_retard_saturated",
        "egt_near_limit",
        "lean_under_load",
        "rod_torque_near_limit",
        "component_health_low",
        "turbo_speed_near_limit",
        "iat_high",
        "hot_spot_near_threshold",
    ]
    t_sim_s: float = Field(ge=0.0)  # s
    lead_time_s: float = Field(ge=0.0)  # s = t_falha − t_sinal
    cylinder: Cylinder | None = None
    value: float
    threshold: float
    unit: str = Field(max_length=16)


class Recommendation(ContractModel):
    rule_id: str = Field(pattern=r"^R-[A-Z]+-[0-9]{2}$")
    action: str = Field(max_length=200)
    table_id: Literal[
        "lambda_target",
        "ignition_base",
        "ignition_trim_cyl",
        "boost_target",
        "boost_target_gear",
        "torque_request",
        "rev_limiter",
        "none",
    ]
    cylinders: list[Cylinder] = Field(default_factory=list)
    value_min: float | None = None
    value_max: float | None = None
    unit: str = Field(max_length=16)
    region: str | None = Field(None, max_length=120)  # ex.: "rpm 3000–6500, MAP ≥ 150 kPa"
    rationale: str = Field(max_length=300)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (
            self.value_min is not None
            and self.value_max is not None
            and self.value_max < self.value_min
        ):
            raise ValueError("value_max deve ser ≥ value_min")
        return self


class NarrativeText(ContractModel):
    title: str = Field(max_length=80)
    summary: str = Field(max_length=280)
    explanation: str = Field(max_length=1200)
    questions: list[str] = Field(default_factory=list, max_length=5)  # só instructor


class TableDelta(ContractModel):
    table_id: str = Field(min_length=1, max_length=64)
    max_delta: float
    unit: str = Field(max_length=16)
    at_rpm: float  # rev/min
    at_load: float  # unidade do eixo de carga


class CalibrationDiff(ContractModel):
    baseline_run_id: Ulid
    baseline_calibration_hash: Sha256Hex
    deltas: list[TableDelta]


class LwTracePoint(ContractModel):
    t_sim_s: float = Field(ge=0.0)  # s
    cylinder: Cylinder
    lw_integral_end: float = Field(ge=0.0)  # (-)
    theta_onset_deg_atdc: float | None  # ° ATDC
    intensity: float = Field(ge=0.0)  # bar


class ForensicReport(ContractModel):
    """Laudo forense de uma puxada (E-14; RF-22 a RF-26)."""

    report_id: Ulid
    report_kind: ReportKind
    run_id: Ulid
    session_id: str = Field(min_length=1, max_length=36)
    vehicle_id: VehicleId
    fuel_id: FuelId
    calibration_hash: Sha256Hex
    seed: int = Field(ge=0, le=2**63 - 1)
    sim_hz: int = Field(ge=100, le=1000)
    failure_event: FailureEvent | None  # None em near_miss sem falha virtual
    primary_mode: FailureMode | None
    damaged_components: list[ComponentHealth]  # health ou virtual_health < 1
    causal_chain: list[CausalLink] = Field(min_length=1, max_length=MAX_CAUSAL_LINKS)
    time_windows: list[TimeWindow]
    early_warnings: list[EarlyWarning]
    recommendations: list[Recommendation] = Field(max_length=8)
    texts: dict[Audience, NarrativeText]  # chaves: valores de Audience
    calibration_diff: CalibrationDiff | None = None
    lw_trace: list[LwTracePoint] = Field(default_factory=list, max_length=200)
    buffer_truncated: bool = False
    simulated_only: bool = False
    generator_version: str = Field(pattern=SEMVER_PATTERN, max_length=16)
    report_sha256: Sha256Hex  # do JSON canônico sem este campo
    created_at: AwareDatetime  # ISO 8601 UTC (fora do laço)

    @model_validator(mode="after")
    def _check(self) -> Self:
        orders = [link.order for link in self.causal_chain]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("causal_chain.order deve ser 1..n sem lacunas")
        times = [link.t_sim_s for link in self.causal_chain]
        if times != sorted(times):
            raise ValueError("causal_chain deve estar em t_sim_s crescente")
        if self.failure_event is not None:
            if any(t > self.failure_event.t_sim_s for t in times):
                raise ValueError("nenhum elo pode ser posterior à falha")
            if self.primary_mode != self.failure_event.mode:
                raise ValueError("primary_mode deve ser o mode do failure_event")
            if self.failure_event.run_id not in (None, self.run_id):
                raise ValueError("failure_event.run_id difere de run_id")
        elif self.report_kind == "failure":
            raise ValueError("laudo 'failure' exige failure_event")
        names = [w.name for w in self.time_windows]
        if len(set(names)) != len(names):
            raise ValueError("time_windows com nome repetido")
        return self
