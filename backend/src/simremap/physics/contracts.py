"""Contratos do barramento do laço físico (engine-physics-core seção 9; simulation-bus 4.2 a 4.8).

Todos os modelos herdam de ``ContractModel`` (``frozen=True``, ``extra="forbid"``).
Listas por cilindro têm comprimento exato ``n_cyl`` (1 a 8), índice 0 = cilindro 1.
No hot path a física usa ``dataclass(slots=True)`` equivalentes; estes modelos são as
formas de fronteira (testes, snapshots decimados, serialização).

Nomes normalizados:
- D-18 / D-BUS-01: ``ignition_advance_deg``, ``throttle_pct``, ``vvt_intake_target_deg``,
  ``vvt_exhaust_target_deg`` (nomes da física, dona do contrato).
- D-20 / D-BUS-11: ``lambda_measured``, ``injector_pw_ms``, ``knock_sensor_v`` (0–5 V) e
  ``knock_intensity`` (0–1).
- D-BUS-03: entradas de condutor e de ECU em ``SensorReadings`` com padrão seguro.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal, Self

from pydantic import Field, model_validator

from simremap.core.contracts import ContractModel

__all__ = [
    "MAX_CYLINDERS",
    "MAX_PHYSICS_FAULTS",
    "SENSOR_BIAS_CHANNELS",
    "ActuatorCommands",
    "CombustionEvent",
    "EngineState",
    "KnockSignal",
    "Pct",
    "PhysicsConfig",
    "PhysicsFault",
    "PhysicsFaultKind",
    "SensorNoiseConfig",
    "SensorReadings",
]

MAX_CYLINDERS: Final = 8
MAX_PHYSICS_FAULTS: Final = 8
DT_TOLERANCE_S: Final = 1e-12

Pct = Annotated[float, Field(ge=0.0, le=100.0)]
"""Percentagem 0..100 %."""

PhysicsFaultKind = Literal[
    "fuel_pump_weak", "injector_clogged", "boost_leak", "sensor_bias", "wastegate_stuck"
]

# Canais de ``SensorReadings`` que aceitam viés (escalares em float).
SENSOR_BIAS_CHANNELS: Final[frozenset[str]] = frozenset(
    {
        "rpm",
        "cam_intake_deg",
        "cam_exhaust_deg",
        "map_kpa",
        "baro_kpa",
        "boost_pre_throttle_kpa",
        "iat_c",
        "ect_c",
        "oil_temp_c",
        "tps_pct",
        "lambda_measured",
        "egt_collector_c",
        "fuel_pressure_kpa",
        "battery_v",
        "oil_pressure_kpa",
        "pedal_pct",
    }
)


def _check_cylinder_lists(name: str, lists: dict[str, list[object] | None]) -> int:
    """Garante que todas as listas por cilindro têm o mesmo comprimento (1..8)."""
    lengths = {key: len(value) for key, value in lists.items() if value is not None}
    distinct = set(lengths.values())
    if len(distinct) != 1:
        raise ValueError(f"{name}: listas por cilindro com comprimentos diferentes: {lengths}")
    n_cyl = distinct.pop()
    if not 1 <= n_cyl <= MAX_CYLINDERS:
        raise ValueError(f"{name}: n_cyl deve estar entre 1 e {MAX_CYLINDERS}, recebeu {n_cyl}")
    return n_cyl


# --------------------------------------------------------------------------- configuração


class SensorNoiseConfig(ContractModel):
    """Desvio-padrão do ruído gaussiano de cada sensor (substreams ``(0,)``)."""

    map_sigma_kpa: float = Field(0.3, ge=0.0)  # kPa
    iat_sigma_c: float = Field(0.2, ge=0.0)  # °C
    ect_sigma_c: float = Field(0.2, ge=0.0)  # °C
    lambda_sigma: float = Field(0.005, ge=0.0)  # (-)
    egt_sigma_c: float = Field(3.0, ge=0.0)  # °C
    rpm_sigma: float = Field(2.0, ge=0.0)  # rev/min
    tps_sigma_pct: float = Field(0.1, ge=0.0)  # %


class PhysicsFault(ContractModel):
    """Falha física injetada (defeitos ocultos dos cenários, physics RF-23).

    Cada ``kind`` exige os seus parâmetros e recusa os dos outros tipos.
    """

    kind: PhysicsFaultKind
    cylinder: int | None = Field(None, ge=1, le=MAX_CYLINDERS)  # injector_clogged
    fuel_pump_max_lph: float | None = Field(None, gt=0.0)  # L/h, fuel_pump_weak
    injector_flow_factor: float | None = Field(None, gt=0.0, le=1.0)  # (-), injector_clogged
    leak_area_mm2: float | None = Field(None, gt=0.0)  # mm², boost_leak
    sensor_channel: str | None = None  # campo de SensorReadings, sensor_bias
    sensor_bias: float | None = None  # unidade do canal, sensor_bias
    stuck_position_pct: float | None = Field(None, ge=0.0, le=100.0)  # %, wastegate_stuck
    start_t_sim_s: float = Field(0.0, ge=0.0)  # s

    @model_validator(mode="after")
    def _check_kind_params(self) -> Self:
        required: dict[str, tuple[str, ...]] = {
            "fuel_pump_weak": ("fuel_pump_max_lph",),
            "injector_clogged": ("cylinder", "injector_flow_factor"),
            "boost_leak": ("leak_area_mm2",),
            "sensor_bias": ("sensor_channel", "sensor_bias"),
            "wastegate_stuck": ("stuck_position_pct",),
        }
        own = required[self.kind]
        missing = [name for name in own if getattr(self, name) is None]
        if missing:
            raise ValueError(f"falha '{self.kind}' exige {', '.join(missing)}")
        others = {name for params in required.values() for name in params} - set(own)
        extra = sorted(name for name in others if getattr(self, name) is not None)
        if extra:
            raise ValueError(f"falha '{self.kind}' não aceita {', '.join(extra)}")
        if self.kind == "sensor_bias" and self.sensor_channel not in SENSOR_BIAS_CHANNELS:
            raise ValueError(f"sensor_channel desconhecido: {self.sensor_channel!r}")
        return self


class PhysicsConfig(ContractModel):
    """Configuração do motor físico (physics RF-01). ``dt = 1 / sim_hz`` fixo."""

    sim_hz: int = Field(1000, ge=100, le=1000)  # Hz
    seed: int = Field(0, ge=0, le=2**63 - 1)
    crank_resolution_deg: float = Field(1.0, ge=1.0, le=1.0)  # °, fixo em 1°
    ambient_pressure_kpa: float = Field(101.325, ge=60.0, le=110.0)  # kPa abs
    ambient_temp_c: float = Field(25.0, ge=-20.0, le=50.0)  # °C
    wall_wetting_enabled: bool | None = None  # None = ligado em PFI, desligado em GDI
    noise_enabled: bool = True
    noise: SensorNoiseConfig = Field(default_factory=SensorNoiseConfig)
    wideband_tau_s: float = Field(0.1, ge=0.02, le=0.5)  # s
    egt_thermocouple_tau_s: float = Field(1.0, ge=0.5, le=1.5)  # s
    wiebe_a: float = Field(5.0, gt=0.0)  # (-)
    wiebe_m: float = Field(2.0, ge=0.0)  # (-)
    cycle_cache_size: int = Field(4096, ge=0, le=65536)  # 0 desliga a cache
    exhaust_backpressure_scale: float = Field(1.0, ge=0.3, le=1.0)  # (-), downpipe
    fuel_pump_capacity_scale: float = Field(1.0, ge=1.0, le=3.0)  # (-), bomba de alta vazão
    faults: list[PhysicsFault] = Field(default_factory=list, max_length=MAX_PHYSICS_FAULTS)

    @property
    def dt(self) -> float:
        """Passo fixo em segundos."""
        return 1.0 / self.sim_hz

    def dt_matches(self, dt: float) -> bool:
        """Indica se ``dt`` coincide com ``1 / sim_hz`` dentro de 1e-12 s (PHYSICS_DT_MISMATCH)."""
        return abs(dt - self.dt) <= DT_TOLERANCE_S


# --------------------------------------------------------------------------- barramento


class KnockSignal(ContractModel):
    """Sinal de knock do último ciclo de cada cilindro (produzido pelo dano, D-14)."""

    intensity: list[Annotated[float, Field(ge=0.0)]] = Field(
        min_length=1, max_length=MAX_CYLINDERS
    )  # escala de MAPO em bar; 0 = sem knock

    @classmethod
    def silent(cls, n_cyl: int) -> KnockSignal:
        """Sinal sem knock para ``n_cyl`` cilindros."""
        return cls(intensity=[0.0] * n_cyl)


class SensorReadings(ContractModel):
    """Leituras de sensores entregues à ECU no início do tick (simulation-bus 4.2)."""

    t_sim_s: float = Field(ge=0.0)  # s
    tick: int = Field(ge=0)
    rpm: float = Field(ge=0.0)  # rev/min
    crank_angle_deg: float = Field(ge=0.0, lt=720.0)  # °, 0 = PMS de compressão do cil. 1
    cam_intake_deg: float  # ° de cambota, posição real do VVT de admissão
    cam_exhaust_deg: float  # ° de cambota
    map_kpa: float = Field(ge=0.0)  # kPa abs
    baro_kpa: float = Field(ge=0.0)  # kPa abs
    boost_pre_throttle_kpa: float = Field(ge=0.0)  # kPa abs, antes da borboleta
    iat_c: float  # °C
    ect_c: float  # °C
    oil_temp_c: float  # °C
    tps_pct: Pct  # %
    lambda_measured: float = Field(ge=0.5, le=2.0)  # (-), wideband saturada
    egt_c: list[float]  # °C por cilindro (termopar)
    egt_collector_c: float  # °C pré-turbina
    fuel_pressure_kpa: float = Field(ge=0.0)  # kPa diferencial do rail
    battery_v: float = Field(ge=6.0, le=16.0)  # V
    knock_sensor_v: list[Annotated[float, Field(ge=0.0, le=5.0)]]  # V por cilindro
    knock_intensity: list[Annotated[float, Field(ge=0.0, le=1.0)]]  # (-) por cilindro
    turbo_rpm: float | None = Field(None, ge=0.0)  # rev/min; None sem turbo
    wastegate_position_pct: Pct | None = None  # %
    # Entradas exigidas pela ECU (D-BUS-03)
    pedal_pct: Pct = 0.0  # %
    gear: int = Field(0, ge=0, le=10)  # 0 = neutro
    vehicle_speed_kmh: float = Field(0.0, ge=0.0)  # km/h
    oil_pressure_kpa: float = Field(0.0, ge=0.0)  # kPa
    clutch_pressed: bool = False
    launch_switch: bool = False
    shift_request: bool = False
    antilag_switch: bool = False
    sync_ok: bool = True
    ethanol_pct: float | None = Field(None, ge=0.0, le=100.0)  # %, sensor flex (None sem flex)

    @property
    def n_cyl(self) -> int:
        return len(self.egt_c)

    @model_validator(mode="after")
    def _check_lengths(self) -> Self:
        _check_cylinder_lists(
            "SensorReadings",
            {
                "egt_c": list(self.egt_c),
                "knock_sensor_v": list(self.knock_sensor_v),
                "knock_intensity": list(self.knock_intensity),
            },
        )
        return self


class ActuatorCommands(ContractModel):
    """Comandos de atuadores produzidos pela ECU (simulation-bus 4.3, nomes D-18)."""

    t_sim_s: float = Field(ge=0.0)  # s
    injector_pw_ms: list[Annotated[float, Field(ge=0.0, le=50.0)]]  # ms por cilindro
    injection_end_deg_btdc: list[Annotated[float, Field(ge=-360.0, le=720.0)]] | None = None
    ignition_advance_deg: list[Annotated[float, Field(ge=-30.0, le=60.0)]]  # ° BTDC, + = avanço
    fuel_cut: list[bool]
    spark_cut: list[bool]
    throttle_pct: Pct  # %, alvo da borboleta eletrónica
    wastegate_duty_pct: Pct = 0.0  # %
    vvt_intake_target_deg: float = 0.0  # ° de cambota
    vvt_exhaust_target_deg: float = 0.0  # ° de cambota
    bypass_open: bool = False  # BOV (turbo) ou bypass (supercharger)
    antilag_air_pct: Pct = 0.0  # %
    fuel_pump_duty_pct: Pct = 100.0  # %

    @property
    def n_cyl(self) -> int:
        return len(self.injector_pw_ms)

    @model_validator(mode="after")
    def _check_lengths(self) -> Self:
        _check_cylinder_lists(
            "ActuatorCommands",
            {
                "injector_pw_ms": list(self.injector_pw_ms),
                "injection_end_deg_btdc": (
                    None
                    if self.injection_end_deg_btdc is None
                    else list(self.injection_end_deg_btdc)
                ),
                "ignition_advance_deg": list(self.ignition_advance_deg),
                "fuel_cut": list(self.fuel_cut),
                "spark_cut": list(self.spark_cut),
            },
        )
        return self


class CombustionEvent(ContractModel):
    """Um ciclo de combustão de um cilindro (simulation-bus 4.4)."""

    cylinder: int = Field(ge=1, le=MAX_CYLINDERS)
    t_sim_s: float = Field(ge=0.0)  # s
    rpm: float = Field(ge=0.0)  # rev/min
    theta_start_deg: float  # ° do primeiro ponto (faísca), ATDC negativo
    pressure_kpa: list[float]  # kPa abs, 1 ponto por grau, faísca → fim de combustão
    t_unburned_k: list[float]  # K
    burned_fraction: list[Annotated[float, Field(ge=0.0, le=1.0)]]  # (-)
    p_max_kpa: float = Field(ge=0.0)  # kPa abs
    theta_pmax_deg_atdc: float  # ° ATDC
    t_unburned_max_k: float = Field(ge=0.0)  # K
    rod_force_peak_n: float  # N
    imep_gross_kpa: float  # kPa
    lambda_real: float | None  # (-), None em corte de combustível
    fuel_octane_ron: float = Field(ge=0.0)
    fuel_octane_mon: float = Field(ge=0.0)
    misfire: bool
    afterfire_energy_j: float = Field(ge=0.0)  # J
    pop_event: bool

    @model_validator(mode="after")
    def _check_traces(self) -> Self:
        lengths = {len(self.pressure_kpa), len(self.t_unburned_k), len(self.burned_fraction)}
        if len(lengths) != 1:
            raise ValueError(
                "pressure_kpa, t_unburned_k e burned_fraction devem ter o mesmo comprimento"
            )
        return self


class EngineState(ContractModel):
    """Estado do motor no fim do tick (simulation-bus 4.4)."""

    t_sim_s: float = Field(ge=0.0)  # s
    tick: int = Field(ge=0)
    rpm: float = Field(ge=0.0)  # rev/min
    crank_angle_deg: float = Field(ge=0.0, lt=720.0)  # °
    locked: bool
    stalled: bool
    map_kpa: float = Field(ge=0.0)  # kPa abs
    boost_pre_throttle_kpa: float = Field(ge=0.0)  # kPa abs
    exhaust_manifold_kpa: float = Field(ge=0.0)  # kPa abs
    t_manifold_c: float  # °C
    t_intercooler_out_c: float | None  # °C
    ve_true: list[float]  # fração (-)
    m_air_mg: list[float]  # mg por ciclo
    m_fuel_mg: list[float]  # mg por ciclo
    lambda_cyl: list[float | None]  # (-), None em corte
    lambda_collector: float | None  # (-)
    ignition_advance_deg: list[float]  # ° BTDC efetivo
    burn_duration_deg: list[float]  # °
    p_max_kpa: list[float]  # kPa abs
    theta_pmax_deg_atdc: list[float]  # ° ATDC
    t_unburned_max_k: list[float]  # K
    rod_force_peak_n: list[float]  # N
    piston_temp_c: list[float]  # °C
    hot_spot_temp_c: list[float]  # °C
    egt_c: list[float]  # °C, gás real (sem termopar)
    egt_collector_c: float  # °C
    imep_gross_kpa: float  # kPa
    pmep_kpa: float  # kPa
    fmep_kpa: float  # kPa
    torque_indicated_nm: float  # N·m
    torque_nm: float  # N·m, freio na cambota
    power_kw: float  # kW
    wheel_power_kw: float  # kW
    whp: float  # hp (1 hp = 0,7457 kW)
    fuel_flow_g_s: float = Field(ge=0.0)  # g/s
    bsfc_g_kwh: float | None  # g/kWh
    thermal_efficiency: float  # (-)
    turbo_rpm: float | None  # rev/min
    compressor_pressure_ratio: float | None  # (-)
    compressor_efficiency: float | None  # (-)
    surge_margin: float | None  # (-), < 0 = surge
    wastegate_position_pct: float | None  # %
    supercharger_rpm: float | None  # rev/min
    supercharger_power_kw: float | None  # kW
    ect_c: float  # °C
    iat_c: float  # °C
    events: list[CombustionEvent] = Field(default_factory=list)  # eventos do tick (0..n)
    real_time_factor: float | None = Field(None, ge=0.0)  # preenchido pelo worker

    @property
    def n_cyl(self) -> int:
        return len(self.ve_true)

    @model_validator(mode="after")
    def _check_lengths(self) -> Self:
        n_cyl = _check_cylinder_lists(
            "EngineState",
            {
                "ve_true": list(self.ve_true),
                "m_air_mg": list(self.m_air_mg),
                "m_fuel_mg": list(self.m_fuel_mg),
                "lambda_cyl": list(self.lambda_cyl),
                "ignition_advance_deg": list(self.ignition_advance_deg),
                "burn_duration_deg": list(self.burn_duration_deg),
                "p_max_kpa": list(self.p_max_kpa),
                "theta_pmax_deg_atdc": list(self.theta_pmax_deg_atdc),
                "t_unburned_max_k": list(self.t_unburned_max_k),
                "rod_force_peak_n": list(self.rod_force_peak_n),
                "piston_temp_c": list(self.piston_temp_c),
                "hot_spot_temp_c": list(self.hot_spot_temp_c),
                "egt_c": list(self.egt_c),
            },
        )
        bad = [event.cylinder for event in self.events if event.cylinder > n_cyl]
        if bad:
            raise ValueError(f"CombustionEvent com cilindro fora de 1..{n_cyl}: {bad}")
        return self
