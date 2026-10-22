"""Contratos de fronteira da ECU genérica (ecu-core seção 9; simulation-bus 3.2 e 4.7).

- ``EcuStatus`` e ``EcuEvent``: snapshot e eventos publicados a cada tick (RF-30, RF-33).
  Nome normalizado D-BUS-01: ``ignition_advance_deg`` (antes ``ign_advance_deg``).
- ``EcuStepResult``: retorno de ``EcuRuntime.step`` (D-BUS-09), ``dataclass(slots=True)``.
- ``StrategyConfig``: união discriminada por ``kind`` das 10 estratégias.
- ``TableKind``, ``AxisQuantity``, ``AXIS_UNITS`` e ``Axis`` (eixo validado), consumidos
  pelos descritores do ecu-profiles; ``ecu/tables.py`` importa-os daqui e acrescenta
  ``Table2D``/``Table3D`` e a interpolação. ``Calibration`` fica em ``ecu/calibration.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from simremap.core.contracts import ContractModel, Sha256Hex
from simremap.physics.contracts import MAX_CYLINDERS, ActuatorCommands

__all__ = [
    "ARBITRATION_PRIORITY",
    "AXIS_MAX_POINTS",
    "AXIS_UNITS",
    "AntilagConfig",
    "Axis",
    "AxisQuantity",
    "BoostControlConfig",
    "ClosedLoopConfig",
    "CutMode",
    "EcuEvent",
    "EcuEventKind",
    "EcuStatus",
    "EcuStepResult",
    "EcuValidationError",
    "FailsafeAction",
    "FailsafeConfig",
    "FailsafeRule",
    "FailsafeRuleId",
    "KnockControlConfig",
    "OverrunConfig",
    "PowershiftConfig",
    "RevLimiterConfig",
    "StrategyBase",
    "StrategyConfig",
    "StrategyKind",
    "TableKind",
    "TwoStepConfig",
    "VvtConfig",
]


AXIS_MAX_POINTS: Final = 32


class EcuValidationError(ValueError):
    """Erro de domínio com ``code`` estável; o router converte em ProblemDetail 422."""

    def __init__(self, code: str, detail: dict[str, object] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail: dict[str, object] = detail or {}


class AxisQuantity(StrEnum):
    RPM = "rpm"  # rev/min
    MAP_KPA = "map_kpa"  # kPa absoluto
    TPS_PCT = "tps_pct"  # %
    PEDAL_PCT = "pedal_pct"  # %
    LOAD_PCT = "load_pct"  # % de enchimento relativo (perfil OEM)
    ECT_C = "ect_c"  # °C
    IAT_C = "iat_c"  # °C
    BATTERY_V = "battery_v"  # V
    GEAR = "gear"  # 0 = neutro, 1..8
    EGT_C = "egt_c"  # °C
    TPS_RATE_PCT_S = "tps_rate_pct_s"  # %/s
    IGN_DELTA_DEG = "ign_delta_deg"  # ° de atraso face ao ótimo
    BOOST_TARGET_KPA = "boost_target_kpa"  # kPa absoluto
    TORQUE_NM = "torque_nm"  # N·m
    ETHANOL_PCT = "ethanol_pct"  # % de etanol lido pelo sensor flex


AXIS_UNITS: Final[dict[str, str]] = {
    "rpm": "rev/min",
    "map_kpa": "kPa",
    "tps_pct": "%",
    "pedal_pct": "%",
    "load_pct": "%",
    "ect_c": "°C",
    "iat_c": "°C",
    "battery_v": "V",
    "gear": "-",
    "egt_c": "°C",
    "tps_rate_pct_s": "%/s",
    "ign_delta_deg": "°",
    "boost_target_kpa": "kPa",
    "torque_nm": "N·m",
    "ethanol_pct": "%",
}


class Axis(ContractModel):
    """Eixo de tabela: 2 a 32 pontos finitos, estritamente crescentes."""

    quantity: AxisQuantity
    values: list[float] = Field(min_length=2)  # máximo 32, validado abaixo

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(self.values) > AXIS_MAX_POINTS:
            raise EcuValidationError("TABLE_SIZE_EXCEEDED", {"points": len(self.values)})
        if not all(isfinite(v) for v in self.values):
            raise EcuValidationError("TABLE_VALUE_NOT_FINITE", {"quantity": self.quantity.value})
        if any(b <= a for a, b in zip(self.values, self.values[1:], strict=False)):
            raise EcuValidationError("TABLE_AXIS_NOT_MONOTONIC", {"quantity": self.quantity.value})
        return self

    @property
    def unit(self) -> str:
        """Unidade do eixo (``AXIS_UNITS``)."""
        return AXIS_UNITS[self.quantity.value]


class TableKind(StrEnum):
    # Standalone e comuns
    VE = "ve"
    INJ_BASE_MS = "inj_base_ms"
    LAMBDA_TARGET = "lambda_target"
    IGNITION_BASE = "ignition_base"
    IGNITION_TRIM_CYL = "ignition_trim_cyl"
    FUEL_TRIM_CYL = "fuel_trim_cyl"
    IGN_CORR_IAT = "ign_corr_iat"
    IGN_CORR_ECT = "ign_corr_ect"
    FUEL_CORR_ECT = "fuel_corr_ect"
    FUEL_CORR_IAT = "fuel_corr_iat"
    ACCEL_ENRICH = "accel_enrich"
    CRANKING_FUEL = "cranking_fuel"
    AFTERSTART_ENRICH = "afterstart_enrich"
    INJ_DEAD_TIME = "inj_dead_time"
    BOOST_TARGET = "boost_target"
    BOOST_TARGET_GEAR = "boost_target_gear"
    BOOST_DUTY_BASE = "boost_duty_base"
    KNOCK_THRESHOLD = "knock_threshold"
    OIL_PRESSURE_MIN = "oil_pressure_min"
    CAM_INTAKE_TARGET = "cam_intake_target"
    CAM_EXHAUST_TARGET = "cam_exhaust_target"
    FLEX_IGN_ADD = "flex_ign_add"
    FLEX_BOOST_ADD = "flex_boost_add"
    # Perfil OEM (semântica definida na spec ecu-profiles)
    TORQUE_REQUEST = "torque_request"
    TORQUE_LIMIT = "torque_limit"
    TORQUE_LIMIT_GEAR = "torque_limit_gear"
    TORQUE_OPTIMAL = "torque_optimal"
    IGNITION_OPTIMAL = "ignition_optimal"
    IGNITION_EFFICIENCY = "ignition_efficiency"
    OEM_PRESSURE_TARGET = "oem_pressure_target"
    FRICTION_TORQUE = "friction_torque"
    LAMBDA_COMPONENT_PROTECTION = "lambda_component_protection"


class StrategyKind(StrEnum):
    CLOSED_LOOP = "closed_loop"
    KNOCK_CONTROL = "knock_control"
    BOOST_CONTROL = "boost_control"
    REV_LIMITER = "rev_limiter"
    TWO_STEP = "two_step"
    ANTILAG = "antilag"
    POWERSHIFT = "powershift"
    OVERRUN = "overrun"
    FAILSAFE = "failsafe"
    VVT = "vvt"


ARBITRATION_PRIORITY: Final[tuple[str, ...]] = (
    "failsafe",
    "rev_limiter",
    "two_step",
    "antilag",
    "powershift",
    "overrun",
    "normal",
)
"""Ordem de arbitragem: failsafe > limitador > two-step/antilag/powershift > overrun > normal."""

CutMode = Literal["fuel_cut", "spark_cut", "rolling_cut"]


def _check_range(name: str, low: float, high: float) -> None:
    if high <= low:
        raise ValueError(f"{name}: o máximo deve ser maior que o mínimo")


class StrategyBase(ContractModel):
    enabled: bool = True


class ClosedLoopConfig(StrategyBase):
    kind: Literal["closed_loop"] = "closed_loop"
    kp: float = Field(default=0.5, ge=0.0, le=5.0)  # fração de trim por fração de erro
    ki_per_s: float = Field(default=2.0, ge=0.0, le=20.0)  # 1/s
    trim_limit_pct: float = Field(default=25.0, ge=0.0, le=25.0)  # %
    min_ect_c: float = Field(default=60.0, ge=-40.0, le=120.0)  # °C
    rpm_min: float = Field(default=800.0, ge=0.0)  # rev/min
    rpm_max: float = Field(default=7500.0, le=12000.0)  # rev/min
    map_max_kpa: float = Field(default=400.0, le=500.0)  # kPa abs
    delay_after_start_s: float = Field(default=10.0, ge=0.0, le=120.0)  # s
    ltft_enabled: bool = False
    ltft_rate_pct_s: float = Field(default=0.5, ge=0.0, le=5.0)  # %/s
    ltft_limit_pct: float = Field(default=15.0, ge=0.0, le=25.0)  # %

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_range("closed_loop rpm", self.rpm_min, self.rpm_max)
        return self


class KnockControlConfig(StrategyBase):
    kind: Literal["knock_control"] = "knock_control"
    retard_step_deg: float = Field(default=2.0, gt=0.0, le=5.0)  # °
    max_retard_deg: float = Field(default=8.0, gt=0.0, le=15.0)  # °
    recovery_hold_s: float = Field(default=0.5, ge=0.0, le=10.0)  # s
    recovery_deg_per_s: float = Field(default=1.0, gt=0.0, le=10.0)  # °/s
    rpm_min: float = Field(default=1500.0, ge=0.0)  # rev/min
    map_min_kpa: float = Field(default=80.0, ge=0.0)  # kPa abs
    boost_reduction_kpa_at_max: float = Field(default=20.0, ge=0.0, le=100.0)  # kPa
    max_retard_hold_s: float = Field(default=2.0, ge=0.1, le=10.0)  # s

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.retard_step_deg > self.max_retard_deg:
            raise ValueError("retard_step_deg não pode exceder max_retard_deg")
        return self


class BoostControlConfig(StrategyBase):
    kind: Literal["boost_control"] = "boost_control"
    mode: Literal["open_loop", "closed_loop"] = "closed_loop"
    kp_pct_per_kpa: float = Field(default=0.4, ge=0.0, le=10.0)  # %/kPa
    ki_pct_per_kpa_s: float = Field(default=0.8, ge=0.0, le=20.0)  # %/(kPa·s)
    kd_pct_s_per_kpa: float = Field(default=0.02, ge=0.0, le=2.0)  # %·s/kPa
    d_filter_tau_s: float = Field(default=0.05, gt=0.0, le=1.0)  # s
    pid_activation_window_kpa: float = Field(default=20.0, ge=0.0, le=200.0)  # kPa
    integrator_limit_pct: float = Field(default=30.0, ge=0.0, le=100.0)  # %
    by_gear_enabled: bool = False
    overboost_kpa: float = Field(default=260.0, ge=100.0, le=500.0)  # kPa abs
    overboost_time_s: float = Field(default=0.1, ge=0.0, le=2.0)  # s
    overboost_hysteresis_kpa: float = Field(default=10.0, ge=0.0, le=50.0)  # kPa
    overboost_cut_mode: Literal["wastegate_open", "fuel_cut", "spark_cut"] = "wastegate_open"


class RevLimiterConfig(StrategyBase):
    kind: Literal["rev_limiter"] = "rev_limiter"
    hard_rpm: float = Field(default=7000.0, ge=1000.0, le=12000.0)  # rev/min
    cut_mode: CutMode = "fuel_cut"
    soft_enabled: bool = True
    soft_window_rpm: float = Field(default=200.0, ge=0.0, le=1000.0)  # rev/min
    soft_retard_max_deg: float = Field(default=10.0, ge=0.0, le=30.0)  # °
    hysteresis_rpm: float = Field(default=100.0, ge=10.0, le=500.0)  # rev/min

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.soft_enabled and self.soft_window_rpm >= self.hard_rpm:
            raise ValueError("soft_window_rpm deve ser menor que hard_rpm")
        return self


class TwoStepConfig(StrategyBase):
    kind: Literal["two_step"] = "two_step"
    target_rpm: float = Field(default=4000.0, ge=1500.0, le=9000.0)  # rev/min
    cut_mode: CutMode = "spark_cut"
    ign_advance_deg: float = Field(default=-5.0, ge=-20.0, le=30.0)  # ° BTDC absoluto
    lambda_target: float = Field(default=0.85, ge=0.65, le=1.0)  # (-)
    activation: Literal["clutch", "launch_switch"] = "clutch"
    max_speed_kmh: float = Field(default=5.0, ge=0.0, le=50.0)  # km/h
    min_tps_pct: float = Field(default=80.0, ge=0.0, le=100.0)  # %
    max_active_s: float = Field(default=10.0, gt=0.0, le=60.0)  # s
    release_ramp_s: float = Field(default=0.2, ge=0.0, le=2.0)  # s


class AntilagConfig(StrategyBase):
    kind: Literal["antilag"] = "antilag"
    activation: Literal["switch", "rolling"] = "switch"  # rolling: entre rpm_min e rpm_max
    rpm_min: float = Field(default=3000.0, ge=1000.0)  # rev/min
    rpm_max: float = Field(default=7000.0, le=12000.0)  # rev/min
    max_tps_pct: float = Field(default=20.0, ge=0.0, le=100.0)  # %
    ign_advance_deg: float = Field(default=-15.0, ge=-20.0, le=10.0)  # ° BTDC absoluto
    lambda_target: float = Field(default=0.80, ge=0.65, le=1.0)  # (-)
    air_valve_pct: float = Field(default=15.0, ge=0.0, le=100.0)  # %
    cut_mode: CutMode = "rolling_cut"
    cut_fraction: float = Field(default=0.25, ge=0.0, le=0.75)  # (-)
    egt_max_c: float = Field(default=1000.0, ge=600.0, le=1150.0)  # °C
    max_active_s: float = Field(default=3.0, gt=0.0, le=30.0)  # s
    cooldown_s: float = Field(default=5.0, ge=0.0, le=120.0)  # s

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_range("antilag rpm", self.rpm_min, self.rpm_max)
        return self


class PowershiftConfig(StrategyBase):
    kind: Literal["powershift"] = "powershift"
    trigger: Literal["shift_request", "clutch"] = "shift_request"
    min_tps_pct: float = Field(default=80.0, ge=0.0, le=100.0)  # %
    min_rpm: float = Field(default=3000.0, ge=0.0)  # rev/min
    cut_mode: Literal["fuel_cut", "spark_cut"] = "spark_cut"
    cut_time_ms: float = Field(default=120.0, ge=20.0, le=500.0)  # ms
    resume_retard_deg: float = Field(default=5.0, ge=0.0, le=20.0)  # °
    resume_ramp_s: float = Field(default=0.15, ge=0.0, le=2.0)  # s


class OverrunConfig(StrategyBase):
    kind: Literal["overrun"] = "overrun"
    dfco_enabled: bool = True
    dfco_tps_max_pct: float = Field(default=2.0, ge=0.0, le=10.0)  # %
    dfco_rpm_min: float = Field(default=1500.0, ge=500.0)  # rev/min
    dfco_resume_rpm: float = Field(default=1200.0, ge=500.0)  # rev/min
    dfco_delay_s: float = Field(default=0.5, ge=0.0, le=5.0)  # s
    pops_enabled: bool = False
    pops_rpm_min: float = Field(default=2500.0, ge=1000.0)  # rev/min
    pops_rpm_max: float = Field(default=6500.0, le=12000.0)  # rev/min
    pops_tps_max_pct: float = Field(default=5.0, ge=0.0, le=20.0)  # %
    fuel_cut_delay_s: float = Field(default=1.5, ge=0.0, le=5.0)  # s
    ign_advance_deg: float = Field(default=-15.0, ge=-20.0, le=10.0)  # ° BTDC absoluto
    lambda_target: float = Field(default=0.90, ge=0.70, le=1.10)  # (-)
    intensity_pct: float = Field(default=60.0, ge=0.0, le=100.0)  # %
    max_duration_s: float = Field(default=2.0, gt=0.0, le=5.0)  # s
    egt_turbine_max_c: float = Field(default=950.0, ge=600.0, le=1100.0)  # °C
    catalyst_present: bool = True
    catalyst_max_intensity_pct: float = Field(default=30.0, ge=0.0, le=100.0)  # %
    catalyst_max_duration_s: float = Field(default=0.5, ge=0.0, le=5.0)  # s

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.dfco_resume_rpm >= self.dfco_rpm_min:
            raise ValueError("dfco_resume_rpm deve ser menor que dfco_rpm_min")
        _check_range("pops rpm", self.pops_rpm_min, self.pops_rpm_max)
        return self


FailsafeAction = Literal[
    "boost_reduce", "boost_cut", "rev_limit_reduce", "enrich", "ignition_retard", "fuel_cut"
]
FailsafeRuleId = Literal[
    "egt_high",
    "egt_critical",
    "lean_under_load",
    "ect_high",
    "oil_pressure_low",
    "overspeed",
    "sensor_fault",
]


class FailsafeRule(ContractModel):
    rule_id: FailsafeRuleId
    enabled: bool = True
    threshold: float  # unidade por regra (Apêndice E)
    confirm_s: float = Field(ge=0.0, le=5.0)  # s
    actions: list[FailsafeAction] = Field(min_length=1)
    action_value: float = 0.0  # kPa (boost_reduce), rpm (rev_limit_reduce), Δλ (enrich), °
    release_s: float = Field(default=2.0, ge=0.0, le=60.0)  # s
    latch_until_stop: bool = False  # true: só libera com RPM < 500

    @model_validator(mode="after")
    def _check(self) -> Self:
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("actions com duplicados")
        return self


class VvtConfig(StrategyBase):
    """Controle de came variável (RF-11): inibição a frio, limite de taxa e offsets."""

    kind: Literal["vvt"] = "vvt"
    min_ect_c: float = Field(default=40.0, ge=-40.0, le=120.0)  # °C: abaixo disto alvos = 0
    max_rate_deg_s: float = Field(default=120.0, gt=0.0, le=1000.0)  # °/s do alvo comandado
    intake_offset_deg: float = Field(default=0.0, ge=-20.0, le=20.0)  # ° somados à tabela
    exhaust_offset_deg: float = Field(default=0.0, ge=-20.0, le=20.0)  # ° somados à tabela


class FailsafeConfig(StrategyBase):
    kind: Literal["failsafe"] = "failsafe"
    rules: list[FailsafeRule]  # padrões no Apêndice E
    overspeed_rpm: float = Field(default=7500.0, ge=1000.0, le=13000.0)  # rev/min

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [rule.rule_id for rule in self.rules]
        if len(set(ids)) != len(ids):
            raise ValueError("rules com rule_id duplicado")
        return self


StrategyConfig = Annotated[
    ClosedLoopConfig
    | KnockControlConfig
    | BoostControlConfig
    | RevLimiterConfig
    | TwoStepConfig
    | AntilagConfig
    | PowershiftConfig
    | OverrunConfig
    | FailsafeConfig
    | VvtConfig,
    Field(discriminator="kind"),
]
"""Configuração de estratégia, discriminada por ``kind`` (10 tipos)."""


# --------------------------------------------------------------------------- barramento

EcuEventKind = Literal[
    "limiter_hit",
    "failsafe_trip",
    "failsafe_release",
    "knock_retard",
    "overboost_cut",
    "inj_duty_high",
    "closed_loop_limit",
    "two_step_timeout",
    "antilag_protect",
    "overrun_protect",
    "sensor_fault",
    "budget_overrun",
]


class EcuEvent(ContractModel):
    t_sim_s: float = Field(ge=0.0)  # s
    kind: EcuEventKind
    cylinder: int | None = Field(None, ge=1, le=MAX_CYLINDERS)
    value: float | None = None
    detail: str = Field("", max_length=200)


class EcuStatus(ContractModel):
    """Snapshot decimado do estado da ECU (no laço: dataclass com slots)."""

    t_sim_s: float = Field(ge=0.0)  # s
    lambda_target: float = Field(gt=0.0)  # (-)
    stft_pct: float = Field(ge=-100.0, le=100.0)  # %
    ltft_pct: float = Field(ge=-100.0, le=100.0)  # %
    closed_loop_active: bool
    fuel_mass_mg: list[float]  # mg por cilindro (comandado)
    injector_pw_ms: list[float]  # ms por cilindro (comandado)
    inj_duty_pct: float = Field(ge=0.0)  # % = pw_ms / (120 000 / rpm) × 100
    ignition_advance_deg: list[float]  # ° BTDC comandado (D-BUS-01)
    knock_retard_deg: list[float]  # ° por cilindro
    boost_target_kpa: float = Field(ge=0.0)  # kPa abs
    wastegate_duty_pct: float = Field(ge=0.0, le=100.0)  # %
    limiter_state: Literal["off", "soft", "hard"]
    active_strategies: list[str]  # kinds de StrategyKind ativos
    arbitration_winner: str = Field(min_length=1, max_length=32)  # failsafe | ... | normal
    failsafe_actions: list[str]  # valores de FailsafeAction ativos
    load_pct: float = Field(ge=0.0, le=300.0)  # % carga relativa
    torque_request_nm: float | None  # N·m; None nos perfis standalone
    calibration_hash: Sha256Hex  # SHA-256 da calibração ativa

    @property
    def n_cyl(self) -> int:
        return len(self.injector_pw_ms)

    @model_validator(mode="after")
    def _check(self) -> Self:
        lengths = {
            len(self.fuel_mass_mg),
            len(self.injector_pw_ms),
            len(self.ignition_advance_deg),
            len(self.knock_retard_deg),
        }
        if len(lengths) != 1:
            raise ValueError("listas por cilindro do EcuStatus com comprimentos diferentes")
        if not 1 <= self.n_cyl <= MAX_CYLINDERS:
            raise ValueError(f"n_cyl deve estar entre 1 e {MAX_CYLINDERS}")
        if self.arbitration_winner not in ARBITRATION_PRIORITY:
            raise ValueError(f"arbitration_winner desconhecido: {self.arbitration_winner!r}")
        return self


@dataclass(slots=True)
class EcuStepResult:
    """Retorno de ``EcuRuntime.step`` (D-BUS-09): comandos, status e eventos do tick."""

    commands: ActuatorCommands
    status: EcuStatus
    events: list[EcuEvent] = field(default_factory=list)  # 0..n por tick

    def __post_init__(self) -> None:
        if self.commands.n_cyl != self.status.n_cyl:
            raise ValueError("commands e status com n_cyl diferente")
