"""Contratos do dinamômetro virtual (dyno-bench seção 9; simulation-bus 4.1 e 4.9).

- ``DynoLoad``: carga entregue à física a cada tick (nomes D-BUS-08 + entradas D-BUS-03).
- Sessão: ``AmbientConditions``, ``DynoRigConfig``, ``SessionCreateRequest`` e
  ``SimulationSession`` (``fuel_id``, ``physics_faults``, ``attempt_id`` da RF-25;
  ``upgrades`` e ``ethanol_pct`` da 002 RF-13/RF-18).
- Puxada: ``DynoRunRequest``, ``ProbeOverrides``, ``RunState``, ``AbortReason``,
  ``DynoRun``, ``DynoCurvePoint``, ``RunSummary`` e ``PullResult``.

Regras que geram códigos próprios (``RPM_RANGE_INVALID``, ``GEAR_NOT_AVAILABLE``,
``PROBE_NOT_ALLOWED``) dependem do veículo ou da sessão e ficam no serviço; os modelos
expõem auxiliares (``DynoRunRequest.rpm_range_ok``) para isso.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from simremap.catalog.contracts import FLEX_FUEL_ID, FuelId, ProfileIdLiteral, VehicleId
from simremap.catalog.upgrades import UpgradePackage
from simremap.core.contracts import ContractModel, Sha256Hex, SimStrEnum
from simremap.physics.contracts import MAX_PHYSICS_FAULTS, PhysicsFault

__all__ = [
    "MIN_RPM_SPAN",
    "RUN_STATE_TRANSITIONS",
    "SEED_MAX",
    "SEED_RANDOM_MAX",
    "TERMINAL_RUN_STATES",
    "AbortReason",
    "AmbientConditions",
    "CorrectionStandard",
    "DynoCurvePoint",
    "DynoLoad",
    "DynoRigConfig",
    "DynoRun",
    "DynoRunRequest",
    "EcuStateLiteral",
    "ProbeOverrides",
    "PullResult",
    "RunId",
    "RunState",
    "RunStatePayload",
    "RunSummary",
    "RunType",
    "SessionCreateRequest",
    "SessionId",
    "SessionState",
    "SimulationSession",
    "SteadyStateCell",
    "UuidText",
    "can_transition",
]

SEED_MAX: Final = 2**63 - 1  # aceito do cliente (sementes antigas e pacotes de cenário)
SEED_RANDOM_MAX: Final = 2**53 - 1  # sorteio do servidor: inteiro exato em JS (T031)
MIN_RPM_SPAN: Final = 500.0
UUID_PATTERN: Final = (
    r"^(?:[0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
ULID_PATTERN: Final = r"^[0-9A-HJKMNP-TV-Z]{26}$"

UuidText = Annotated[str, Field(pattern=UUID_PATTERN, max_length=36)]
"""UUID4 em hex (32) ou com hífens (36), minúsculo."""

SessionId = UuidText
RunId = Annotated[str, Field(pattern=ULID_PATTERN)]
"""ULID (Crockford base32 maiúsculo, 26 caracteres), ordenável."""

SessionState = Literal["ready", "running", "engine_locked", "closed"]
EcuStateLiteral = Literal["oem", "awaiting_base_setup", "standalone_ready"]

OddWindow = Annotated[int, Field(ge=1, le=11)]
PidGains = tuple[float, float, float]  # Kp, Ki, Kd


class RunType(SimStrEnum):
    BASELINE_PULL = "baseline_pull"
    SWEEP_PULL = "sweep_pull"
    STEADY_STATE_HOLD = "steady_state_hold"
    MULTI_PULL = "multi_pull"


class RunState(SimStrEnum):
    IDLE = "idle"
    ARMING = "arming"
    RUNNING = "running"
    COASTDOWN = "coastdown"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ENGINE_FAILED = "engine_failed"


class AbortReason(SimStrEnum):
    USER_ABORT = "user_abort"
    EGT_LIMIT = "egt_limit"
    SEVERE_KNOCK_PROTECTION = "severe_knock_protection"
    CATASTROPHIC_FAILURE = "catastrophic_failure"
    ARMING_TIMEOUT = "arming_timeout"
    SESSION_CLOSED = "session_closed"
    RUN_TIMEOUT = "run_timeout"
    INTERNAL_ERROR = "internal_error"


class CorrectionStandard(SimStrEnum):
    SAE_J1349 = "sae_j1349"
    DIN_70020 = "din_70020"
    NONE = "none"


TERMINAL_RUN_STATES: Final[frozenset[RunState]] = frozenset(
    {RunState.COMPLETED, RunState.ABORTED, RunState.ENGINE_FAILED}
)

RUN_STATE_TRANSITIONS: Final[dict[RunState, frozenset[RunState]]] = {
    RunState.IDLE: frozenset({RunState.ARMING}),
    RunState.ARMING: frozenset({RunState.RUNNING, RunState.ABORTED, RunState.ENGINE_FAILED}),
    RunState.RUNNING: frozenset({RunState.COASTDOWN, RunState.ABORTED, RunState.ENGINE_FAILED}),
    RunState.COASTDOWN: frozenset({RunState.COMPLETED, RunState.ENGINE_FAILED}),
    RunState.COMPLETED: frozenset(),
    RunState.ABORTED: frozenset(),
    RunState.ENGINE_FAILED: frozenset(),
}
"""Tabela de transições da máquina de estados da puxada (dyno RF-13, seção 8)."""


def can_transition(current: RunState, target: RunState) -> bool:
    """Indica se a transição ``current → target`` está na tabela da seção 8."""
    return target in RUN_STATE_TRANSITIONS[current]


def _require_odd(name: str, value: int) -> None:
    if value % 2 == 0:
        raise ValueError(f"{name} deve ser ímpar")


# --------------------------------------------------------------------------- sessão


class AmbientConditions(ContractModel):
    temperature_c: float = Field(25.0, ge=-20.0, le=50.0)  # °C
    pressure_kpa: float = Field(99.0, ge=60.0, le=110.0)  # kPa barométrica absoluta
    relative_humidity: float = Field(0.0, ge=0.0, le=1.0)  # fração 0..1


class DynoRigConfig(ContractModel):
    roller_inertia_kg_m2: float = Field(300.0, gt=10.0, le=5000.0)  # kg·m²
    roller_radius_m: float = Field(0.6096, gt=0.1, le=1.0)  # m
    loss_c0_nm: float = Field(2.0, ge=0.0)  # N·m
    loss_c1_nm_s_rad: float = Field(0.05, ge=0.0)  # N·m·s/rad
    absorber_tau_s: float = Field(0.05, gt=0.0, le=1.0)  # s
    absorber_cap_nm: float = Field(3000.0, gt=0.0)  # N·m
    absorber_omega_c_rad_s: float = Field(10.0, gt=0.0)  # rad/s
    absorber_max_power_kw: float = Field(600.0, gt=0.0)  # kW
    rpm_pid: PidGains = (2.0, 4.0, 0.02)  # Kp, Ki, Kd
    load_pid: PidGains = (0.5, 2.0, 0.0)  # Kp, Ki, Kd
    accel_window_ticks: int = Field(21, ge=5, le=101)  # ímpar
    fan_air_speed_m_s: float = Field(12.0, ge=0.0, le=30.0)  # m/s

    @model_validator(mode="after")
    def _check(self) -> Self:
        _require_odd("accel_window_ticks", self.accel_window_ticks)
        for name in ("rpm_pid", "load_pid"):
            if any(gain < 0.0 for gain in getattr(self, name)):
                raise ValueError(f"{name}: ganhos devem ser ≥ 0")
        return self


class SessionCreateRequest(ContractModel):
    """Pedido de ``POST /api/v1/sessions`` (E-06)."""

    vehicle_id: VehicleId
    calibration_id: str | None = Field(None, min_length=1, max_length=64)  # None ⇒ de série
    profile_id: ProfileIdLiteral = "oem-stage"  # EcuProfileId
    seed: int | None = Field(None, ge=0, le=SEED_MAX)  # None ⇒ sorteada em [0, 2^53 − 1]
    sim_hz: int = Field(1000, ge=100, le=1000)  # Hz
    ambient: AmbientConditions = Field(default_factory=AmbientConditions)
    correction_standard: CorrectionStandard = CorrectionStandard.SAE_J1349
    rig: DynoRigConfig = Field(default_factory=DynoRigConfig)
    operator_protection: bool = False  # modo instrutor (RF-16)
    egt_abort_enabled: bool = True
    damage_enabled: bool = True  # consumido pelo knock-and-failure-model
    fuel_id: FuelId | None = None  # None ⇒ combustível de série do veículo
    physics_faults: list[PhysicsFault] = Field(
        default_factory=list, max_length=MAX_PHYSICS_FAULTS
    )  # defeitos ocultos (engine-physics-core)
    attempt_id: UuidText | None = None  # tentativa do training-scenarios
    upgrades: UpgradePackage = Field(default_factory=UpgradePackage)  # oficina (002 RF-13)
    ethanol_pct: float | None = Field(None, ge=27.0, le=100.0)  # %, flex (002 RF-18)

    @model_validator(mode="after")
    def _check_flex(self) -> Self:
        if self.ethanol_pct is not None and self.fuel_id not in (None, FLEX_FUEL_ID):
            raise ValueError("ethanol_pct exige fuel_id 'flex' ou omitido")
        if self.fuel_id == FLEX_FUEL_ID and self.ethanol_pct is None:
            raise ValueError("fuel_id 'flex' exige ethanol_pct (27–100 %)")
        return self


class SimulationSession(SessionCreateRequest):
    """Sessão de simulação (resposta de E-06 e E-07)."""

    session_id: SessionId
    seed: int = Field(ge=0, le=SEED_MAX)  # semente efetiva
    calibration_id: str = Field(min_length=1, max_length=64)  # calibração inicial efetiva
    # Calibração em uso pelo worker (T031): muda com "Aplicar" (E-20), ``ecu/swap`` e
    # ``ecu/base-setup`` com mapa. ``None`` só em sessões gravadas antes do campo (⇒ use
    # ``calibration_id``).
    active_calibration_id: str | None = Field(None, min_length=1, max_length=64)
    active_calibration_version: int | None = Field(None, ge=1)
    fuel_id: FuelId  # combustível efetivo
    state: SessionState
    ecu_state: EcuStateLiteral = "oem"  # D-REST-06
    active_run_id: RunId | None = None
    baseline_run_id: RunId | None = None
    engine_locked: bool = False
    realtime_factor: float | None = Field(None, ge=0.0)
    t_sim_s: float = Field(0.0, ge=0.0)  # s
    created_at: AwareDatetime  # ISO 8601 UTC (relógio de parede fora do laço)


# --------------------------------------------------------------------------- barramento


class DynoLoad(ContractModel):
    """Carga do dinamômetro entregue à física a cada tick (simulation-bus 4.1)."""

    reflected_inertia_kg_m2: float = Field(ge=0.0)  # kg·m², J_refl no virabrequim
    load_torque_crank_nm: float = Field(ge=0.0)  # N·m, T_load_crank
    gear: int = Field(ge=0, le=10)  # 0 = neutro
    wheel_to_crank_ratio: float = Field(ge=0.0)  # G / k (-)
    pedal_pct: float = Field(ge=0.0, le=100.0)  # %, entrada do operador da bancada
    fan_air_speed_m_s: float = Field(ge=0.0)  # m/s
    ambient: AmbientConditions
    vehicle_speed_kmh: float = Field(0.0, ge=0.0)  # km/h (D-BUS-03)
    clutch_pressed: bool = False
    launch_switch: bool = False
    shift_request: bool = False
    antilag_switch: bool = False


# --------------------------------------------------------------------------- puxada


class ProbeOverrides(ContractModel):
    """Ajustes de puxadas de sonda sem UI (training-scenarios; dyno RF-26)."""

    ignition_offset_deg: float = Field(0.0, ge=-10.0, le=10.0)  # °, após a arbitragem da ECU
    knock_control_open_loop: bool = False  # True ⇒ retardo de knock fixo em 0°
    damage_enabled: bool = False  # sondas nunca danificam o motor

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.damage_enabled:
            raise ValueError("sondas não aceitam damage_enabled = true")
        return self


class SteadyStateCell(ContractModel):
    rpm: float = Field(ge=500.0, le=12000.0)  # rev/min
    map_kpa: float | None = Field(None, ge=20.0, le=400.0)  # kPa abs
    pedal_pct: float | None = Field(None, ge=0.0, le=100.0)  # %
    hold_s: float = Field(3.0, ge=1.0, le=30.0)  # s

    @model_validator(mode="after")
    def _one_load_target(self) -> Self:
        if (self.map_kpa is None) == (self.pedal_pct is None):
            raise ValueError("exatamente um de map_kpa ou pedal_pct")
        return self


class DynoRunRequest(ContractModel):
    """Pedido de ``POST /api/v1/sessions/{session_id}/runs`` (E-09)."""

    run_type: RunType
    gear: int = Field(4, ge=1, le=10)
    start_rpm: float = Field(2000.0, ge=1000.0, le=10000.0)  # rev/min
    end_rpm: float | None = Field(None, ge=1500.0, le=12000.0)  # None ⇒ rev_limit − 200
    pedal_pct: float = Field(100.0, ge=0.0, le=100.0)  # %
    ramp_rate_rpm_s: float = Field(300.0, ge=50.0, le=1000.0)  # rev/min/s
    cells: list[SteadyStateCell] = Field(default_factory=list, max_length=64)
    cell_timeout_s: float = Field(10.0, ge=2.0, le=60.0)  # s
    pull_count: int = Field(3, ge=2, le=10)
    pull_type: Literal["sweep_pull", "baseline_pull"] = "sweep_pull"
    cooldown_s: float = Field(60.0, ge=0.0, le=600.0)  # s
    fan_on: bool = True
    smoothing_window: OddWindow = 5  # ímpar 1..11
    label: str | None = Field(None, max_length=80)
    probe: ProbeOverrides | None = None  # só puxadas de sonda (RF-26)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _require_odd("smoothing_window", self.smoothing_window)
        if self.run_type == RunType.STEADY_STATE_HOLD and not self.cells:
            raise ValueError("steady_state_hold exige cells não vazio")
        if self.run_type != RunType.STEADY_STATE_HOLD and self.cells:
            raise ValueError("cells só é aceito em steady_state_hold")
        return self

    def effective_end_rpm(self, rev_limit_rpm: float) -> float:
        """``end_rpm`` limitado ao ``rev_limit_rpm``; omitido vale ``rev_limit_rpm − 200``."""
        if self.end_rpm is None:
            return rev_limit_rpm - 200.0
        return min(self.end_rpm, rev_limit_rpm)

    def rpm_range_ok(self, rev_limit_rpm: float) -> bool:
        """Falso quando ``end_rpm ≤ start_rpm + 500`` (422 ``RPM_RANGE_INVALID``)."""
        return self.effective_end_rpm(rev_limit_rpm) > self.start_rpm + MIN_RPM_SPAN


class DynoCurvePoint(ContractModel):
    """Ponto agregado (25 rpm) da curva de potência."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )

    rpm: float = Field(ge=0.0)  # rev/min
    t_sim_s: float = Field(ge=0.0)  # s
    power_wheel_kw: float  # kW
    power_wheel_kw_corr: float  # kW corrigida
    power_crank_kw: float  # kW
    power_crank_kw_corr: float  # kW corrigida
    torque_wheel_nm: float  # N·m
    torque_engine_nm: float  # N·m
    torque_engine_nm_corr: float  # N·m corrigido
    lambda_: float = Field(alias="lambda", ge=0.0)  # (-)
    afr: float = Field(ge=0.0)  # (-)
    egt_c: float  # °C pré-turbina
    map_kpa: float = Field(ge=0.0)  # kPa abs
    iat_c: float  # °C
    ect_c: float  # °C
    oil_c: float  # °C
    ignition_deg_btdc: float  # ° BTDC
    knock_retard_max_deg: float = Field(ge=0.0)  # °
    cell_index: int | None = Field(None, ge=0)  # só steady_state_hold
    stable: bool | None = None


class RunSummary(ContractModel):
    """Resumo persistido da puxada (dyno RF-18)."""

    peak_whp: float  # whp
    peak_whp_rpm: float  # rev/min
    peak_power_crank_kw: float  # kW
    peak_torque_engine_nm: float  # N·m
    peak_torque_rpm: float  # rev/min
    lambda_min: float  # (-), pedal ≥ 90 %
    lambda_max: float  # (-), pedal ≥ 90 %
    egt_max_c: float  # °C
    iat_max_c: float  # °C
    correction_factor: float = Field(gt=0.0)  # (-)
    correction_out_of_range: bool
    knock_events: int = Field(ge=0)
    event_codes: list[str] = Field(default_factory=list)
    failure_event_id: str | None = None
    forensic_report_url: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.lambda_max < self.lambda_min:
            raise ValueError("lambda_max deve ser ≥ lambda_min")
        return self


class PullResult(ContractModel):
    pull_index: int = Field(ge=0)
    state: RunState
    summary: RunSummary
    curve: list[DynoCurvePoint]


class DynoRun(ContractModel):
    """Puxada (resposta de E-09, E-10 e E-11)."""

    run_id: RunId
    session_id: SessionId
    run_type: RunType
    request: DynoRunRequest
    state: RunState
    abort_reason: AbortReason | None = None
    started_at_tick: int = Field(ge=0)
    ended_at_tick: int | None = Field(None, ge=0)
    calibration_id: str = Field(min_length=1, max_length=64)
    calibration_hash: Sha256Hex  # SHA-256 da calibração aplicada
    seed: int = Field(ge=0, le=SEED_MAX)
    sim_hz: int = Field(ge=100, le=1000)
    summary: RunSummary | None = None
    curve: list[DynoCurvePoint] = Field(default_factory=list)
    pulls: list[PullResult] = Field(default_factory=list)  # só multi_pull
    repeatability: dict[str, float] | None = None  # peak_whp_spread_pct, peak_torque_spread_pct
    curve_sha256: Sha256Hex | None = None
    persisted: bool = True  # false quando a gravação falhou (EC-04)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.request.run_type != self.run_type:
            raise ValueError("run_type difere de request.run_type")
        if self.state == RunState.ABORTED and self.abort_reason is None:
            raise ValueError("o estado aborted exige abort_reason")
        if self.abort_reason is not None and self.state not in (
            RunState.ABORTED,
            RunState.ENGINE_FAILED,
        ):
            raise ValueError("abort_reason só é aceito em aborted ou engine_failed")
        if self.ended_at_tick is not None and self.ended_at_tick < self.started_at_tick:
            raise ValueError("ended_at_tick deve ser ≥ started_at_tick")
        if self.pulls and self.run_type != RunType.MULTI_PULL:
            raise ValueError("pulls só é aceito em multi_pull")
        return self


class RunStatePayload(ContractModel):
    """Payload do envelope ``run.state`` (1 por transição; websocket-telemetry 3.2)."""

    session_id: SessionId
    run_id: RunId | None
    run_type: RunType | None
    state: RunState
    previous_state: RunState | None
    phase: str | None = Field(None, max_length=24)  # ex.: "pull", "cooldown"
    pull_index: int | None = Field(None, ge=1)
    pull_count: int | None = Field(None, ge=1)
    abort_reason: AbortReason | None = None
    progress_pct: float | None = Field(None, ge=0.0, le=100.0)  # %
    rpm: float = Field(0.0, ge=0.0)  # rev/min
    realtime_factor: float | None = Field(None, ge=0.0)
    forensic_report_url: str | None = None  # preenchido em engine_failed
