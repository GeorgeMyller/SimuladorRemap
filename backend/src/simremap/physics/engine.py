"""``PhysicsEngine``: motor Otto 0D/1D de passo fixo (engine-physics-core; simulation-bus 3.1).

Ordem interna do ``step()`` (determinística, seção 8 da spec):

1. validar ``commands`` e ``dt`` (antes de alterar qualquer estado);
2. atuadores com dinâmica própria: borboleta (τ 30 ms + limite de 600 %/s), VVT (1.ª ordem
   com ``VvtSpec.actuator_tau_s`` + limite de 150 °/s), wastegate (τ 50 ms);
3. volumes de gás (boost, coletor, escape) e eixo do turbo em subpassos ``h = dt / k``;
4. avanço de θ e resolução, por ordem de ângulo, de cada evento cujo IVC cai no tick;
5. torque médio, dinâmica rotacional, temperaturas lumpadas, EGT e filtros dos sensores.

O tempo simulado é sempre ``t_sim_s = tick / sim_hz`` (D-07); o ruído usa só os
``Generator(PCG64)`` semeados de ``sensors.SensorNoise``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Final

from simremap.catalog.contracts import FLEX_FUEL_ID, FuelSpec, VehicleSpec
from simremap.dyno.contracts import DynoLoad
from simremap.physics import digest as _digest
from simremap.physics.combustion import flammable
from simremap.physics.config import ResolvedConfig, check_dt, resolve_config
from simremap.physics.contracts import (
    ActuatorCommands,
    CombustionEvent,
    EngineState,
    KnockSignal,
    PhysicsConfig,
    SensorReadings,
)
from simremap.physics.cycle_solver import CycleResult, CycleSolver, quantize_inputs
from simremap.physics.errors import (
    ACTUATOR_COMMAND_INVALID,
    PHYSICS_CONFIG_INVALID,
    PHYSICS_FUEL_CHANGE_WHILE_RUNNING,
    PHYSICS_NUMERIC_DIVERGENCE,
    PHYSICS_SNAPSHOT_INVALID,
    PhysicsError,
)
from simremap.physics.exhaust import (
    COLLECTOR_TAU_S,
    CYLINDER_GAS_TAU_S,
    EGT_PROBE_UA_FRACTION,
    EXH_MANIFOLD_UA_W_K_PER_L23,
    EXH_MANIFOLD_WALL_ABOVE_ECT_K,
    exhaust_event,
    first_order,
    manifold_heat_loss,
)
from simremap.physics.fastmodel import fast_constructor
from simremap.physics.faults import ActiveFaults
from simremap.physics.friction import (
    brake_torque_nm,
    chen_flynn_fmep_kpa,
    engine_inertia_kg_m2,
    imep_kpa,
    pmep_kpa,
    power_kw,
    rpm_rate_per_s,
    wheel_power_kw,
)
from simremap.physics.fuel import (
    T_RESIDUAL_K,
    InjectorModel,
    TrueVolumetricEfficiency,
    ValveOverlap,
    WallFilm,
    evaporative_cooling_k,
    residual_fraction,
    trapped_air_kg,
)
from simremap.physics.geometry import CrankSchedule, CylinderGeometry, mean_piston_speed
from simremap.physics.kernels import build_gas_kernel, build_thermal_kernel, use_native
from simremap.physics.manifold import (
    CD_THROTTLE,
    R_AIR,
    linear_implicit_step,
    orifice_flow,
    throttle_area_m2,
)
from simremap.physics.sensors import (
    KNOCK_SIGMA_V,
    SensorNoise,
    clamp_lambda,
    knock_index,
    knock_voltage,
    wideband_update,
)
from simremap.physics.supercharger import (
    BYPASS_AREA_M2,
    PRE_COMPRESSOR_PLENUM_M3,
    SuperchargerModel,
)
from simremap.physics.thermal import (
    HOT_SPOT_TAU_S,
    PISTON_TAU_S,
    CoolantModel,
    hot_spot_target_c,
    oil_pressure_kpa,
    oil_temp_rate,
    piston_target_c,
    relax,
)
from simremap.physics.turbo import (
    CompressorMap,
    IntercoolerModel,
    TurbineModel,
    compressor_inlet_flow_limit,
    rad_s_to_rpm,
    rpm_to_rad_s,
    shaft_acceleration,
    wastegate_target,
)

__all__ = ["EngineVars", "PhysicsEngine"]

# Construtores sem validação do hot path (equivalentes a ``model_construct``; T025).
_NEW_ENGINE_STATE: Final = fast_constructor(EngineState)
_NEW_SENSOR_READINGS: Final = fast_constructor(SensorReadings)
_NEW_COMBUSTION_EVENT: Final = fast_constructor(CombustionEvent)

K0: Final = 273.15
THROTTLE_TAU_S: Final = 0.030
THROTTLE_SLEW_PCT_S: Final = 600.0  # limite do motor da borboleta eletrónica (inferido)
VVT_RATE_DEG_S: Final = 150.0
WASTEGATE_TAU_S: Final = 0.050
RAIL_TAU_S: Final = 0.2
WALL_ABOVE_ECT_K: Final = 80.0  # T_wall = ECT + 80 K
STALL_RPM: Final = 300.0
STARTER_RPM: Final = 250.0
STARTER_RELEASE_RPM: Final = 400.0
STARTER_MAX_S: Final = 3.0
LOCK_STOP_S: Final = 0.4  # o bloqueio leva o RPM a 0 em 0,4 s (≤ 0,5 s, RF-19)
OVERREV_FACTOR: Final = 1.15
BATTERY_RUNNING_V: Final = 14.0
BATTERY_OFF_V: Final = 12.4
BOV_AREA_M2: Final = 5e-4
ANTILAG_AREA_M2: Final = 2e-4
COMPRESSOR_PASSIVE_K: Final = 237.0  # kg/(s·m²) de fluxo bloqueado de referência
EXHAUST_BACKPRESSURE_KPA: Final = 15.0  # Δp do catalisador/silencioso a ṁ_ref (inferido)
EXHAUST_REF_FLOW_PER_L: Final = 0.12  # kg/s por litro de cilindrada (inferido)
NA_EXHAUST_AREA_CM2_PER_L: Final = 6.0  # área efetiva do escape sem turbo (inferido)
T_DIVERGENCE_K: Final = 4000.0
LOAD_REF_KPA: Final = 2000.0  # IMEP de referência para a fração de carga do óleo
ETHANOL_SENSOR_DITHER_PCT: Final = 0.3  # %, ruído determinístico do sensor flex (sem RNG)
# Downpipe (002 RF-16, inferido): com menos contrapressão pós-turbina o gás deixa o coletor
# mais depressa; o excesso T_col − T_parede cai 8 % por unidade de (1 − escala).
DOWNPIPE_EGT_GAIN: Final = 0.08


@dataclass(slots=True)
class EngineVars:
    """Estado completo e canónico do motor (ordem dos campos = ordem do digest)."""

    tick: int = 0
    rpm: float = 0.0
    theta_deg: float = 0.0
    locked: bool = False
    stalled: bool = False
    lock_rate_rpm_s: float = 0.0
    starter_s: float = 0.0
    throttle_pct: float = 0.0
    vvt_in_deg: float = 0.0
    vvt_ex_deg: float = 0.0
    wastegate_x: float = 0.0
    p_boost_kpa: float = 101.325
    p_man_kpa: float = 101.325
    p_exh_kpa: float = 101.325
    t_boost_k: float = 298.15
    t_man_k: float = 298.15
    turbo_omega: float = 0.0
    ic_core_k: float = 298.15
    m_comp_kg_s: float = 0.0
    m_exh_out_kg_s: float = 0.0
    surge_s: float = -1.0
    rail_dp_kpa: float = 0.0
    ect_c: float = 25.0
    oil_c: float = 25.0
    egt_col_k: float = 298.15
    tc_col_c: float = 25.0
    wb_filtered: float = 2.0
    wb_index: int = 0
    p_amb_kpa: float = 101.325
    t_amb_k: float = 298.15
    fan_m_s: float = 0.0
    pedal_pct: float = 0.0
    gear: int = 0
    vehicle_speed_kmh: float = 0.0
    clutch_pressed: bool = False
    launch_switch: bool = False
    shift_request: bool = False
    antilag_switch: bool = False
    ring_count: int = 0
    ring_index: int = 0
    lambda_col_last: float = 2.0
    fuel_rate_kg_s: float = 0.0
    m_throttle_cum_kg: float = 0.0
    m_trapped_cum_kg: float = 0.0
    events_total: int = 0
    wb_buffer: list[float] = field(default_factory=list)
    ring_work_j: list[float] = field(default_factory=list)
    ring_pmax_kpa: list[float] = field(default_factory=list)
    film_kg: list[float] = field(default_factory=list)
    egt_gas_k: list[float] = field(default_factory=list)
    tc_egt_c: list[float] = field(default_factory=list)
    piston_c: list[float] = field(default_factory=list)
    hot_spot_c: list[float] = field(default_factory=list)
    ve_last: list[float] = field(default_factory=list)
    m_air_last: list[float] = field(default_factory=list)
    m_fuel_last: list[float] = field(default_factory=list)
    lam_last: list[float] = field(default_factory=list)  # NaN = None
    adv_last: list[float] = field(default_factory=list)
    burn_last: list[float] = field(default_factory=list)
    pmax_last: list[float] = field(default_factory=list)
    thpk_last: list[float] = field(default_factory=list)
    tumax_last: list[float] = field(default_factory=list)
    frod_last: list[float] = field(default_factory=list)
    qwall_last: list[float] = field(default_factory=list)
    port_k_last: list[float] = field(default_factory=list)
    fire_last: list[float] = field(default_factory=list)


@dataclass(slots=True)
class _Flows:
    """Vazões e grandezas auxiliares num ponto de pressões (diagnóstico do tick)."""

    m_thr: float = 0.0
    m_comp: float = 0.0
    m_eng: float = 0.0
    m_turb: float = 0.0
    m_wg: float = 0.0
    m_out: float = 0.0
    p_turb_w: float = 0.0
    p_comp_w: float = 0.0
    t_comp_out_k: float = 0.0
    pr_comp: float = 1.0
    eta_comp: float = 0.0
    surge_margin: float = 1.0
    sc_power_kw: float = 0.0
    sc_rpm: float = 0.0
    ve: float = 0.0


class PhysicsEngine:
    """Motor físico de um veículo (API pública da seção 8 da spec)."""

    def __init__(  # noqa: PLR0915
        self,
        config: PhysicsConfig,
        vehicle: VehicleSpec,
        fuel: FuelSpec,
        *,
        initial_ect_c: float | None = None,
        ethanol_pct: float | None = None,
        native: bool | None = None,
    ) -> None:
        self.resolved: ResolvedConfig = resolve_config(config, vehicle, fuel)
        self.config = config
        self.vehicle = vehicle
        self.fuel = fuel
        self.ethanol_pct = _flex_ethanol_pct(fuel, ethanol_pct)
        eng = vehicle.engine
        self.n_cyl = eng.n_cyl
        self.geo = CylinderGeometry.from_engine(eng)
        self.crank_schedule = CrankSchedule.from_engine(eng)
        self.ve_model = TrueVolumetricEfficiency(
            eng, ValveOverlap.from_vehicle(vehicle) if eng.vvt is not None else None
        )
        self.injector = InjectorModel(vehicle.injectors, fuel)
        self.direct_injection = eng.injection_type == "gdi"
        self.film = WallFilm(self.resolved.wall_wetting, self.direct_injection)
        native_on = use_native(native)
        self.solver = CycleSolver(
            self.geo, eng, config.wiebe_a, config.wiebe_m, config.cycle_cache_size, native=native_on
        )
        self.fuel_index = self.solver.register_fuel(fuel)
        self.faults = ActiveFaults(config.faults, self.n_cyl)
        self.noise = SensorNoise(config.seed)
        self.coolant = CoolantModel()
        self.j_engine = engine_inertia_kg_m2(eng.displacement_cc)
        self.induction = vehicle.induction
        self.turbine = TurbineModel(vehicle.turbo) if vehicle.turbo is not None else None
        self.compressor = (
            CompressorMap(vehicle.turbo.compressor) if vehicle.turbo is not None else None
        )
        self.sc = SuperchargerModel(vehicle.supercharger) if vehicle.supercharger else None
        self.pre_compressor = eng.throttle_location == "pre_compressor"
        self.intercooler = IntercoolerModel(eng.intercooler)
        self.v_man = eng.intake_manifold_volume_l * 1e-3
        self.v_exh = eng.exhaust_manifold_volume_l * 1e-3
        if self.pre_compressor:
            self.v_boost = PRE_COMPRESSOR_PLENUM_M3
        elif eng.boost_volume_l is not None:
            self.v_boost = eng.boost_volume_l * 1e-3
        else:
            self.v_boost = 3.0e-3
        self.has_boost_volume = self.induction != "natural"
        self.throttle_d = eng.throttle_diameter_mm / 1000.0
        disp_l = eng.displacement_cc / 1000.0
        self.exh_ref_flow = EXHAUST_REF_FLOW_PER_L * disp_l
        self.exh_backpressure_kpa, self.egt_backpressure_factor = _backpressure(config)
        self.na_exhaust_area = NA_EXHAUST_AREA_CM2_PER_L * disp_l * 1e-4
        if self.compressor is not None:
            self.comp_passive_area = self.compressor.spec.m_choke_max_kg_s / COMPRESSOR_PASSIVE_K
        else:
            self.comp_passive_area = 0.0
        self.max_rpm = vehicle.mechanical_limits.max_rpm * OVERREV_FACTOR
        self.recip_kg = eng.recip_mass_g / 1000.0
        self.exh_ua_w_k = EXH_MANIFOLD_UA_W_K_PER_L23 * eng.exhaust_manifold_volume_l ** (2 / 3)
        self._initial_ect_c = initial_ect_c
        # Bloco de gás nativo (feature 003): um ``GasKernel.step`` por tick; senão Python.
        self._gas_kernel: Any = None
        self._thermal_kernel: Any = None
        if native_on:
            try:
                self._gas_kernel = build_gas_kernel(self)
                self._thermal_kernel = build_thermal_kernel(self)
            except ValueError:
                if native:  # exigido explicitamente: não esconder o erro
                    raise
                self._gas_kernel = None
                self.solver.disable_native()  # dados que o kernel não aceita: tudo em Python
        self.vars = EngineVars()
        self._init_vars(self.config.ambient_pressure_kpa, self.config.ambient_temp_c + K0)
        self.last_reason: str | None = None

    # ================================================================== estado
    def _init_vars(self, p_amb: float, t_amb: float) -> None:
        n = self.n_cyl
        v = self.vars
        old_tick = v.tick
        new = EngineVars()
        new.tick = old_tick
        new.p_amb_kpa = p_amb
        new.t_amb_k = t_amb
        new.p_boost_kpa = new.p_man_kpa = new.p_exh_kpa = p_amb
        new.t_boost_k = new.t_man_k = new.ic_core_k = new.egt_col_k = t_amb
        ect = self._initial_ect_c if self._initial_ect_c is not None else t_amb - K0
        new.ect_c = ect
        new.oil_c = ect
        new.tc_col_c = t_amb - K0
        new.wb_buffer = [2.0] * self.resolved.wideband_buffer_len
        new.ring_work_j = [0.0] * n
        new.ring_pmax_kpa = [0.0] * n
        new.film_kg = [0.0] * n
        new.egt_gas_k = [t_amb] * n
        new.tc_egt_c = [t_amb - K0] * n
        new.piston_c = [ect] * n
        new.hot_spot_c = [ect] * n
        new.ve_last = [0.0] * n
        new.m_air_last = [0.0] * n
        new.m_fuel_last = [0.0] * n
        new.lam_last = [math.nan] * n
        new.adv_last = [0.0] * n
        new.burn_last = [0.0] * n
        new.pmax_last = [p_amb] * n
        new.thpk_last = [0.0] * n
        new.tumax_last = [t_amb] * n
        new.frod_last = [0.0] * n
        new.qwall_last = [0.0] * n
        new.port_k_last = [t_amb] * n
        new.fire_last = [0.0] * n
        new.rail_dp_kpa = self._rail_target(100.0, None)
        self.vars = new

    def _rail_target(self, pump_duty_pct: float, demand_lph: float | None) -> float:
        """Pressão diferencial de rail alvo (kPa) com o teto da bomba fraca."""
        inj = self.vehicle.injectors
        if inj.pressure_reference == "cylinder":
            target = min(
                max(inj.rail_pressure_max_kpa * pump_duty_pct / 100.0, inj.rail_pressure_min_kpa),
                inj.rail_pressure_max_kpa,
            )
        else:
            target = inj.dp_ref_kpa * max(pump_duty_pct, 0.0) / 100.0
        cap = self.faults.fuel_pump_max_lph(self.vars.tick / self.resolved.sim_hz)
        if cap is not None:
            cap *= self.config.fuel_pump_capacity_scale  # bomba de alta vazão (upgrade)
        if cap is not None and demand_lph is not None and demand_lph > cap:
            target *= (cap / demand_lph) ** 2  # vazão ∝ √Δp ⇒ Δp cai com o quadrado
        return target

    # ================================================================== API pública
    @property
    def t_sim_s(self) -> float:
        return self.vars.tick / self.resolved.sim_hz

    @property
    def rpm(self) -> float:
        return self.vars.rpm

    def crank(self, rpm: float = STARTER_RPM) -> None:
        """Motor de arranque / acionamento da bancada: põe o eixo a ``rpm`` (EC-06).

        Com ``rpm`` ≤ 400 o motor de arranque segura 250 rpm até o motor pegar (≤ 3 s).
        """
        v = self.vars
        if v.locked:
            return
        v.stalled = False
        v.rpm = min(max(rpm, 0.0), self.max_rpm)
        v.starter_s = STARTER_MAX_S if v.rpm <= STARTER_RELEASE_RPM else 0.0

    def lock(self, reason: str) -> None:
        """Bloqueio mecânico pedido pelo dano: sem combustão a partir do próximo tick."""
        v = self.vars
        v.locked = True
        v.lock_rate_rpm_s = max(v.rpm / LOCK_STOP_S, 1000.0)
        v.starter_s = 0.0
        self.last_reason = reason

    def reset_mechanical(self) -> None:
        """Repõe o motor a 0 rpm e temperaturas do ambiente (o ruído continua a sua sequência)."""
        v = self.vars
        self._init_vars(v.p_amb_kpa, v.t_amb_k)
        self.vars.ect_c = self.vars.oil_c = v.t_amb_k - K0
        self.vars.piston_c = [v.t_amb_k - K0] * self.n_cyl
        self.vars.hot_spot_c = [v.t_amb_k - K0] * self.n_cyl
        self.last_reason = None

    def set_fuel(self, fuel: FuelSpec, ethanol_pct: float | None = None) -> None:
        """Troca o combustível (só com o motor parado, EC-10); ``flex`` exige ``ethanol_pct``."""
        if self.vars.rpm > 0.0:
            raise PhysicsError(
                PHYSICS_FUEL_CHANGE_WHILE_RUNNING,
                f"troca de combustível com o motor a {self.vars.rpm:.0f} rpm",
            )
        resolve_config(self.config, self.vehicle, fuel)
        self.ethanol_pct = _flex_ethanol_pct(fuel, ethanol_pct)
        self.fuel = fuel
        self.injector.set_fuel(fuel)
        self.fuel_index = self.solver.register_fuel(fuel)

    def state_payload(self) -> bytes:
        return _digest.pack_state(self.vars)

    def state_digest(self) -> str:
        """SHA-256 hex do estado canónico (variáveis + geradores de ruído)."""
        return _digest.state_digest(self.state_payload(), self.noise.state_bytes())

    def _meta(self) -> dict[str, object]:
        return {
            "vehicle_id": self.vehicle.vehicle_id,
            "data_version": self.vehicle.data_version,
            "fuel_id": self.fuel.fuel_id,
            "sim_hz": self.resolved.sim_hz,
            "seed": str(self.config.seed),
            "n_cyl": self.n_cyl,
        }

    def snapshot(self) -> bytes:
        """Cabeçalho JSON canónico + vetor float64 LE (sem pickle)."""
        return _digest.write_snapshot(
            self.state_payload(), _digest.layout_of(self.vars), self.noise.state(), self._meta()
        )

    def restore(self, blob: bytes) -> None:
        """Restaura um snapshot; em erro mantém o estado atual intacto (EC-11)."""
        header, payload = _digest.read_snapshot(blob)
        meta = header.get("meta")
        if meta != self._meta():
            raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "snapshot de outro motor ou combustível")
        candidate = EngineVars()
        for f_name in candidate.__slots__:
            current = getattr(self.vars, f_name)
            setattr(candidate, f_name, list(current) if isinstance(current, list) else current)
        _digest.unpack_state(candidate, payload, header["layout"])
        rng = header.get("rng")
        if not isinstance(rng, dict):
            raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "estado dos geradores ausente")
        backup = self.noise.state()
        try:
            self.noise.set_state(rng)
        except (KeyError, TypeError, ValueError) as exc:
            self.noise.set_state(backup)
            raise PhysicsError(PHYSICS_SNAPSHOT_INVALID, "estado dos geradores inválido") from exc
        self.vars = candidate

    # ================================================================== auxiliares
    def true_ve(self) -> float:
        """VE física atual (privilegiada: só testes e pilotos de referência, nunca a ECU)."""
        v = self.vars
        return self.ve_model(v.rpm, v.p_man_kpa, v.p_exh_kpa, v.vvt_in_deg, v.vvt_ex_deg)

    def trapped_air_kg(self) -> float:
        """Massa de ar que o próximo evento aprisionaria (privilegiada)."""
        v = self.vars
        return trapped_air_kg(self.true_ve(), v.p_man_kpa, v.t_man_k, self.geo.vd_cyl_m3)

    def injection_dp_kpa(self) -> float:
        """Pressão diferencial no bico (kPa)."""
        v = self.vars
        inj = self.vehicle.injectors
        if inj.pressure_reference == "cylinder":
            return max(v.rail_dp_kpa - v.p_man_kpa, 0.0)
        if inj.pressure_reference == "atmosphere":
            return max(v.rail_dp_kpa - (v.p_man_kpa - v.p_amb_kpa), 0.0)
        return v.rail_dp_kpa

    def battery_v(self) -> float:
        return BATTERY_RUNNING_V if self.vars.rpm > 500.0 else BATTERY_OFF_V  # noqa: PLR2004

    # ================================================================== sensores
    def read_sensors(self, knock_signal: KnockSignal | None = None) -> SensorReadings:
        """Leituras do estado atual com ruído semeado e filtros (RF-17, RF-26)."""
        v = self.vars
        cfg = self.config
        n = self.n_cyl
        noise_on = cfg.noise_enabled
        sig = cfg.noise
        nz = self.noise
        if noise_on:
            e_map = nz.normal("map", sig.map_sigma_kpa)
            e_iat = nz.normal("iat", sig.iat_sigma_c)
            e_ect = nz.normal("ect", sig.ect_sigma_c)
            e_lam = nz.normal("lambda", sig.lambda_sigma)
            e_egt = nz.normals("egt", sig.egt_sigma_c, n + 1)
            e_rpm = nz.normal("rpm", sig.rpm_sigma)
            e_tps = nz.normal("tps", sig.tps_sigma_pct)
            e_knock = nz.normals("knock", KNOCK_SIGMA_V, n)
        else:
            e_map = e_iat = e_ect = e_lam = e_rpm = e_tps = 0.0
            e_egt = [0.0] * (n + 1)
            e_knock = [0.0] * n
        intensity = knock_signal.intensity if knock_signal is not None else [0.0] * n
        if len(intensity) != n:
            raise PhysicsError(
                ACTUATOR_COMMAND_INVALID, f"KnockSignal com {len(intensity)} cilindros ≠ {n}"
            )
        knock_v = [knock_voltage(intensity[i], e_knock[i]) for i in range(n)]
        knock_i = [knock_index(x) for x in knock_v]
        t = self.t_sim_s
        values: dict[str, float] = {
            "rpm": max(v.rpm + (e_rpm if v.rpm > 0.0 else 0.0), 0.0),
            "cam_intake_deg": v.vvt_in_deg,
            "cam_exhaust_deg": v.vvt_ex_deg,
            "map_kpa": max(v.p_man_kpa + e_map, 0.0),
            "baro_kpa": v.p_amb_kpa,
            "boost_pre_throttle_kpa": (
                v.p_boost_kpa
                if (self.has_boost_volume and not self.pre_compressor)
                else v.p_amb_kpa
            ),
            "iat_c": v.t_man_k - K0 + e_iat,
            "ect_c": v.ect_c + e_ect,
            "oil_temp_c": v.oil_c,
            "tps_pct": min(max(v.throttle_pct + e_tps, 0.0), 100.0),
            "lambda_measured": v.wb_filtered + e_lam,
            "egt_collector_c": v.tc_col_c + e_egt[n],
            "fuel_pressure_kpa": self.injection_dp_kpa(),
            "battery_v": self.battery_v(),
            "oil_pressure_kpa": oil_pressure_kpa(v.rpm, v.oil_c, v.locked),
            "pedal_pct": v.pedal_pct,
        }
        egt = [v.tc_egt_c[i] + e_egt[i] for i in range(n)]
        if self.faults:
            for channel, bias in self.faults.sensor_bias(t).items():
                values[channel] = values[channel] + bias
        values["lambda_measured"] = clamp_lambda(values["lambda_measured"])
        values["tps_pct"] = min(max(values["tps_pct"], 0.0), 100.0)
        values["pedal_pct"] = min(max(values["pedal_pct"], 0.0), 100.0)
        values["battery_v"] = min(max(values["battery_v"], 6.0), 16.0)
        for key in (
            "rpm",
            "map_kpa",
            "baro_kpa",
            "boost_pre_throttle_kpa",
            "fuel_pressure_kpa",
            "oil_pressure_kpa",
        ):
            values[key] = max(values[key], 0.0)
        turbo_rpm = rad_s_to_rpm(v.turbo_omega) if self.turbine is not None else None
        wg_pct = v.wastegate_x * 100.0 if self.turbine is not None else None
        values_any: dict[str, Any] = dict(values)
        values_any["ethanol_pct"] = self._ethanol_reading(v.tick)
        return _NEW_SENSOR_READINGS(
            t_sim_s=t,
            tick=v.tick,
            crank_angle_deg=v.theta_deg,
            egt_c=egt,
            knock_sensor_v=knock_v,
            knock_intensity=knock_i,
            turbo_rpm=turbo_rpm,
            wastegate_position_pct=wg_pct,
            gear=v.gear,
            vehicle_speed_kmh=v.vehicle_speed_kmh,
            clutch_pressed=v.clutch_pressed,
            launch_switch=v.launch_switch,
            shift_request=v.shift_request,
            antilag_switch=v.antilag_switch,
            sync_ok=True,
            **values_any,
        )

    def _ethanol_reading(self, tick: int) -> float | None:
        """Sensor flex: teor do blend com ruído determinístico pequeno (``None`` sem flex)."""
        pct = self.ethanol_pct
        if pct is None:
            return None
        if not self.config.noise_enabled:
            return pct
        dither = math.sin(0.37 * tick) * math.cos(0.051 * tick)
        return min(max(pct + ETHANOL_SENSOR_DITHER_PCT * dither, 0.0), 100.0)

    # ================================================================== validação
    def _validate(self, cmd: ActuatorCommands) -> None:
        n = self.n_cyl
        lists = (cmd.injector_pw_ms, cmd.ignition_advance_deg, cmd.fuel_cut, cmd.spark_cut)
        if any(len(x) != n for x in lists) or (
            cmd.injection_end_deg_btdc is not None and len(cmd.injection_end_deg_btdc) != n
        ):
            raise PhysicsError(
                ACTUATOR_COMMAND_INVALID, f"listas por cilindro devem ter n_cyl={n} elementos"
            )
        for pw in cmd.injector_pw_ms:
            if not (0.0 <= pw <= 50.0):  # noqa: PLR2004
                raise PhysicsError(ACTUATOR_COMMAND_INVALID, f"injector_pw_ms fora de 0–50: {pw}")
        for adv in cmd.ignition_advance_deg:
            if not (-30.0 <= adv <= 60.0):  # noqa: PLR2004
                raise PhysicsError(ACTUATOR_COMMAND_INVALID, f"ignition_advance_deg fora: {adv}")
        for name in ("throttle_pct", "wastegate_duty_pct", "antilag_air_pct", "fuel_pump_duty_pct"):
            val = getattr(cmd, name)
            if not (0.0 <= val <= 100.0):  # noqa: PLR2004
                raise PhysicsError(ACTUATOR_COMMAND_INVALID, f"{name} fora de 0–100: {val}")
        if not (
            math.isfinite(cmd.vvt_intake_target_deg) and math.isfinite(cmd.vvt_exhaust_target_deg)
        ):
            raise PhysicsError(ACTUATOR_COMMAND_INVALID, "alvo de VVT não finito")

    # ================================================================== passo
    def step(self, commands: ActuatorCommands, dyno_load: DynoLoad, dt: float) -> EngineState:
        """Avança um tick ``dt = 1/sim_hz`` (simulation-bus 3.1)."""
        check_dt(self.config, dt)
        self._validate(commands)
        v = self.vars
        t0 = v.tick / self.resolved.sim_hz
        # Entradas do tick (ambiente e condutor vêm do DynoLoad).
        amb = dyno_load.ambient
        v.p_amb_kpa = amb.pressure_kpa
        v.t_amb_k = amb.temperature_c + K0
        v.fan_m_s = dyno_load.fan_air_speed_m_s
        v.pedal_pct = dyno_load.pedal_pct
        v.gear = dyno_load.gear
        v.vehicle_speed_kmh = dyno_load.vehicle_speed_kmh
        v.clutch_pressed = dyno_load.clutch_pressed
        v.launch_switch = dyno_load.launch_switch
        v.shift_request = dyno_load.shift_request
        v.antilag_switch = dyno_load.antilag_switch
        self._actuators(commands, dt, t0)
        flows = self._gas(commands, dt, t0)
        events = self._events(commands, dt, t0)
        state = self._finish(commands, dyno_load, dt, flows, events)
        self._check_divergence()
        return state

    # ------------------------------------------------------------------ atuadores
    def _actuators(self, cmd: ActuatorCommands, dt: float, t0: float) -> None:
        v = self.vars
        target = cmd.throttle_pct
        move = (1.0 - math.exp(-dt / THROTTLE_TAU_S)) * (target - v.throttle_pct)
        limit = THROTTLE_SLEW_PCT_S * dt
        v.throttle_pct += min(max(move, -limit), limit)
        vvt = self.vehicle.engine.vvt
        if vvt is not None:
            # 1.ª ordem com τ do atuador e limite de taxa do fasador (O(1) por tick).
            gain = 1.0 - math.exp(-dt / vvt.actuator_tau_s)
            step = VVT_RATE_DEG_S * dt
            tgt_in = min(max(cmd.vvt_intake_target_deg, vvt.intake_min_deg), vvt.intake_max_deg)
            v.vvt_in_deg += min(max(gain * (tgt_in - v.vvt_in_deg), -step), step)
            if vvt.exhaust_min_deg is not None and vvt.exhaust_max_deg is not None:
                tgt_ex = min(
                    max(cmd.vvt_exhaust_target_deg, vvt.exhaust_min_deg), vvt.exhaust_max_deg
                )
                v.vvt_ex_deg += min(max(gain * (tgt_ex - v.vvt_ex_deg), -step), step)
        turbo = self.vehicle.turbo
        if turbo is not None:
            stuck = self.faults.wastegate_stuck_fraction(t0) if self.faults else None
            if stuck is not None:
                v.wastegate_x = stuck
            else:
                x_cmd = wastegate_target(
                    v.p_boost_kpa,
                    v.p_amb_kpa,
                    cmd.wastegate_duty_pct,
                    turbo.wastegate_spring_kpa,
                    turbo.wastegate_full_open_delta_kpa,
                )
                v.wastegate_x = first_order(v.wastegate_x, x_cmd, dt, WASTEGATE_TAU_S)

    # ------------------------------------------------------------------ gás
    def _flows(  # noqa: PLR0912, PLR0915
        self,
        x: list[float],
        cmd: ActuatorCommands,
        omega: float,
        leak: float,
        diag: _Flows | None,
    ) -> list[float]:
        """Taxas ``dp/dt`` (kPa/s) do vetor de pressões ``x`` (layout por arranjo)."""
        v = self.vars
        p_amb = v.p_amb_kpa
        t_amb = v.t_amb_k
        if self.has_boost_volume:
            p_b, p_m, p_e = x[0], x[1], x[2]
        else:
            p_b, p_m, p_e = p_amb, x[0], x[1]
        p_m = max(p_m, 0.5)
        p_e = max(p_e, 0.5)
        p_b = max(p_b, 0.5)
        rpm = v.rpm
        t_m = v.t_man_k
        t_b = v.t_boost_k
        t_e = v.egt_col_k
        area_thr = CD_THROTTLE * throttle_area_m2(v.throttle_pct, self.throttle_d)
        ve = self.ve_model(rpm, p_m, p_e, v.vvt_in_deg, v.vvt_ex_deg) if rpm > 0.0 else 0.0
        m_eng = ve * 1000.0 * p_m / (R_AIR * t_m) * self.geo.vd_total_m3 * rpm / 120.0
        m_fuel = v.fuel_rate_kg_s
        m_comp = m_thr = m_bypass = m_al = m_leak = 0.0
        p_turb = p_comp = 0.0
        sc_kw = sc_rpm = 0.0
        pr = 1.0
        eta = 0.0
        surge = 1.0
        t_comp_out = t_amb
        p04 = p_amb + self.exh_backpressure_kpa * (v.m_exh_out_kg_s / self.exh_ref_flow) ** 2
        rates: list[float]
        if self.induction == "turbo":
            if self.compressor is None or self.turbine is None:  # pragma: no cover
                raise RuntimeError("turbo sem compressor/turbina")
            dp_ic = self.intercooler.pressure_drop_kpa(v.m_comp_kg_s)
            pr = (p_b + dp_ic) / p_amb
            point = self.compressor.operate(pr, rad_s_to_rpm(omega), p_amb, t_amb)
            m_comp = point.mass_flow_kg_s
            if v.surge_s >= 0.0:
                m_comp *= 1.0 + 0.05 * math.sin(2.0 * math.pi * 8.0 * v.surge_s) * math.exp(
                    -v.surge_s / 0.5
                )
            if p_b < p_amb:
                m_comp = max(
                    m_comp, compressor_inlet_flow_limit(p_amb, t_amb, p_b, self.comp_passive_area)
                )
            p_comp = m_comp * 1005.0 * (point.t_out_k - t_amb)
            eta = point.efficiency
            surge = point.surge_margin
            t_comp_out = point.t_out_k
            m_thr = orifice_flow(area_thr, p_b, t_b, p_m, t_m)
            if (
                cmd.bypass_open
                and self.vehicle.turbo is not None
                and self.vehicle.turbo.blow_off_valve
            ):
                m_bypass = orifice_flow(BOV_AREA_M2, p_b, t_b, p_amb, t_amb)
            m_leak = orifice_flow(leak, p_b, t_b, p_amb, t_amb)
            if cmd.antilag_air_pct > 0.0:
                m_al = max(
                    orifice_flow(ANTILAG_AREA_M2 * cmd.antilag_air_pct / 100.0, p_b, t_b, p_e, t_e),
                    0.0,
                )
            m_t = self.turbine.flow(p_e, t_e, p04)
            m_wg = self.turbine.wastegate_flow(v.wastegate_x, p_e, t_e, p04)
            p_turb = self.turbine.power_w(m_t, p_e, t_e, p04)
            c_b = R_AIR * t_b / self.v_boost / 1000.0
            c_m = R_AIR * t_m / self.v_man / 1000.0
            c_e = 287.0 * t_e / self.v_exh / 1000.0
            rates = [
                c_b * (m_comp - m_thr - m_bypass - m_leak - m_al),
                c_m * (m_thr - m_eng),
                c_e * (m_eng + m_fuel + m_al - m_t - m_wg),
            ]
        else:
            m_t = 0.0
            m_wg = orifice_flow(self.na_exhaust_area, p_e, t_e, p04, t_e, 1.33, 287.0)
            c_m = R_AIR * t_m / self.v_man / 1000.0
            c_e = 287.0 * t_e / self.v_exh / 1000.0
            if self.induction == "natural":
                m_thr = orifice_flow(area_thr, p_amb, t_amb, p_m, t_m)
                m_leak = -orifice_flow(leak, p_m, t_m, p_amb, t_amb)  # entrada de ar falso
                rates = [c_m * (m_thr + m_leak - m_eng), c_e * (m_eng + m_fuel - m_wg)]
            else:
                if self.sc is None:  # pragma: no cover
                    raise RuntimeError("supercharger ausente")
                c_b = R_AIR * t_b / self.v_boost / 1000.0
                if self.pre_compressor:
                    m_thr = orifice_flow(area_thr, p_amb, t_amb, p_b, t_amb)
                    sc = self.sc.operate(rpm, p_b, t_amb, p_m)
                    if cmd.bypass_open and self.sc.spec.bypass_valve:
                        m_bypass = orifice_flow(BYPASS_AREA_M2, p_m, t_m, p_b, t_amb)
                    m_leak = orifice_flow(leak, p_m, t_m, p_amb, t_amb)
                    rates = [
                        c_b * (m_thr - sc.mass_flow_kg_s + m_bypass),
                        c_m * (sc.mass_flow_kg_s - m_bypass - m_eng - m_leak),
                        c_e * (m_eng + m_fuel - m_wg),
                    ]
                else:
                    sc = self.sc.operate(rpm, p_amb, t_amb, p_b)
                    if cmd.bypass_open and self.sc.spec.bypass_valve:
                        m_bypass = orifice_flow(BYPASS_AREA_M2, p_b, t_b, p_amb, t_amb)
                    m_thr = orifice_flow(area_thr, p_b, t_b, p_m, t_m)
                    m_leak = orifice_flow(leak, p_b, t_b, p_amb, t_amb)
                    rates = [
                        c_b * (sc.mass_flow_kg_s - m_bypass - m_thr - m_leak),
                        c_m * (m_thr - m_eng),
                        c_e * (m_eng + m_fuel - m_wg),
                    ]
                m_comp = sc.mass_flow_kg_s
                sc_kw = sc.power_kw
                sc_rpm = sc.rotor_rpm
                t_comp_out = sc.t_out_k
                pr = (p_m / p_b) if self.pre_compressor else (p_b / p_amb)
                eta = sc.adiabatic_efficiency
        if diag is not None:
            diag.m_thr = m_thr
            diag.m_comp = m_comp
            diag.m_eng = m_eng
            diag.m_turb = m_t
            diag.m_wg = m_wg
            diag.m_out = m_t + m_wg
            diag.p_turb_w = p_turb
            diag.p_comp_w = p_comp
            diag.t_comp_out_k = t_comp_out
            diag.pr_comp = pr
            diag.eta_comp = eta
            diag.surge_margin = surge
            diag.sc_power_kw = sc_kw
            diag.sc_rpm = sc_rpm
            diag.ve = ve
        return rates

    @property
    def native(self) -> bool:
        """``True`` quando o gás e o ciclo correm nos kernels Rust (``simremap_rs.cycle``)."""
        return self._gas_kernel is not None

    def _gas(self, cmd: ActuatorCommands, dt: float, t0: float) -> _Flows:
        if self._gas_kernel is not None:
            return self._gas_native(cmd, t0)
        return self._gas_py(cmd, dt, t0)

    def _gas_native(self, cmd: ActuatorCommands, t0: float) -> _Flows:
        """``_gas_py`` num só ``GasKernel.step`` (mesma ordem de operações, D-03)."""
        v = self.vars
        leak = self.faults.leak_cd_area_m2(t0) if self.faults else 0.0
        out = self._gas_kernel.step(
            [
                v.p_amb_kpa,
                v.t_amb_k,
                v.fan_m_s,
                v.rpm,
                v.throttle_pct,
                v.vvt_in_deg,
                v.vvt_ex_deg,
                v.wastegate_x,
                v.fuel_rate_kg_s,
                v.egt_col_k,
                v.p_boost_kpa,
                v.p_man_kpa,
                v.p_exh_kpa,
                v.t_boost_k,
                v.t_man_k,
                v.turbo_omega,
                v.ic_core_k,
                v.m_comp_kg_s,
                v.m_exh_out_kg_s,
                v.surge_s,
                v.m_throttle_cum_kg,
            ],
            cmd.bypass_open,
            cmd.antilag_air_pct,
            leak,
        )
        (
            v.p_boost_kpa,
            v.p_man_kpa,
            v.p_exh_kpa,
            v.turbo_omega,
            v.surge_s,
            v.ic_core_k,
            v.t_boost_k,
            v.t_man_k,
            v.m_comp_kg_s,
            v.m_exh_out_kg_s,
            v.m_throttle_cum_kg,
        ) = out[:11]
        return _Flows(*out[11:])

    def _gas_py(self, cmd: ActuatorCommands, dt: float, t0: float) -> _Flows:
        v = self.vars
        res = self.resolved
        h = res.h
        leak = self.faults.leak_cd_area_m2(t0) if self.faults else 0.0
        turbo = self.vehicle.turbo
        diag = _Flows()
        for _ in range(res.n_substeps):
            omega = v.turbo_omega
            if self.has_boost_volume:
                x = [v.p_boost_kpa, v.p_man_kpa, v.p_exh_kpa]
            else:
                x = [v.p_man_kpa, v.p_exh_kpa]
            f0 = self._flows(x, cmd, omega, leak, diag)
            a1 = 0.0
            if turbo is not None:
                a1 = shaft_acceleration(
                    omega,
                    diag.p_turb_w,
                    diag.p_comp_w,
                    turbo.rotor_inertia_kg_m2,
                    turbo.bearing_friction_k,
                )
                omega_pred = max(omega + h * a1, 0.0)
            else:
                omega_pred = 0.0

            def rates(xx: list[float] | tuple[float, ...], om: float = omega) -> list[float]:
                return self._flows(list(xx), cmd, om, leak, None)

            x_new = linear_implicit_step(rates, x, h, f0)  # type: ignore[arg-type]
            x_new = [max(p, 1.0) for p in x_new]
            if self.has_boost_volume:
                v.p_boost_kpa, v.p_man_kpa, v.p_exh_kpa = x_new
            else:
                v.p_man_kpa, v.p_exh_kpa = x_new
                v.p_boost_kpa = v.p_amb_kpa
            self._flows(x_new, cmd, omega_pred, leak, diag)
            if turbo is not None:
                a2 = shaft_acceleration(
                    omega_pred,
                    diag.p_turb_w,
                    diag.p_comp_w,
                    turbo.rotor_inertia_kg_m2,
                    turbo.bearing_friction_k,
                )
                v.turbo_omega = max(omega + 0.5 * h * (a1 + a2), 0.0)
                v.surge_s = (
                    (v.surge_s + h if v.surge_s >= 0.0 else 0.0)
                    if diag.surge_margin < 0.0
                    else -1.0
                )
            # Intercooler, temperaturas dos volumes e contadores de massa.
            ic = self.intercooler
            if self.induction != "natural":
                v.ic_core_k += h * ic.core_rate(
                    v.ic_core_k, diag.t_comp_out_k, diag.m_comp, v.t_amb_k, v.fan_m_s
                )
                t_out = (
                    ic.outlet_temp(diag.t_comp_out_k, v.ic_core_k) if ic.spec else diag.t_comp_out_k
                )
                if self.pre_compressor:
                    v.t_boost_k = v.t_amb_k
                    v.t_man_k = t_out
                else:
                    v.t_boost_k = t_out
                    v.t_man_k = t_out
            else:
                v.t_boost_k = v.t_man_k = v.t_amb_k
            v.m_comp_kg_s = diag.m_comp
            v.m_exh_out_kg_s = diag.m_out
            v.m_throttle_cum_kg += h * diag.m_thr
        return diag

    # ------------------------------------------------------------------ eventos
    def _events(self, cmd: ActuatorCommands, dt: float, t0: float) -> list[CombustionEvent]:
        v = self.vars
        rpm = v.rpm
        delta = 6.0 * rpm * dt
        out: list[CombustionEvent] = []
        if rpm > 0.0 and not v.locked:
            eng = self.vehicle.engine
            ivc_local = -180.0 + eng.ivc_deg_abdc - v.vvt_in_deg
            crossings = self.crank_schedule.crossings(v.theta_deg, delta, ivc_local)
            if crossings:
                ivc_deg = round(ivc_local)
                evo_deg = round(180.0 - eng.evo_deg_bbdc - v.vvt_ex_deg)
                factors = self.faults.injector_factors(t0) if self.faults else None
                for offset, idx in crossings:
                    t_ev = t0 + offset / (6.0 * rpm)
                    out.append(self._fire(cmd, idx, ivc_deg, evo_deg, t_ev, factors))
        v.theta_deg = (v.theta_deg + delta) % 720.0
        return out

    def _fire(  # noqa: PLR0915, PLR0917
        self,
        cmd: ActuatorCommands,
        idx: int,
        ivc_deg: int,
        evo_deg: int,
        t_ev: float,
        factors: list[float] | None,
    ) -> CombustionEvent:
        v = self.vars
        fuel = self.fuel
        rpm = v.rpm
        afr = fuel.afr_stoich
        ve_model = self.ve_model
        gas_kernel = self._gas_kernel
        if gas_kernel is not None:
            ve = gas_kernel.ve(rpm, v.p_man_kpa, v.p_exh_kpa, v.vvt_in_deg, v.vvt_ex_deg)
        else:
            ve = ve_model(rpm, v.p_man_kpa, v.p_exh_kpa, v.vvt_in_deg, v.vvt_ex_deg)
        m_air = trapped_air_kg(ve, v.p_man_kpa, v.t_man_k, self.geo.vd_cyl_m3)
        fuel_cut = cmd.fuel_cut[idx]
        spark_cut = cmd.spark_cut[idx]
        m_inj = 0.0
        if not fuel_cut:
            factor = factors[idx] if factors is not None else 1.0
            m_inj = self.injector.mass_kg(
                cmd.injector_pw_ms[idx], self.injection_dp_kpa(), self.battery_v(), factor
            )
        m_cyl, v.film_kg[idx] = self.film.step(v.film_kg[idx], m_inj, 120.0 / rpm, v.ect_c)
        lam = m_air / (m_cyl * afr) if m_cyl > 0.0 else None
        fire = (not fuel_cut) and (not spark_cut) and lam is not None and flammable(lam)
        misfire = (not fuel_cut) and not fire
        m_fuel_cycle = m_cyl if not fuel_cut else 0.0
        overlap_scale = 1.0
        if ve_model.overlap is not None:
            d = ve_model.overlap.delta(rpm, v.vvt_in_deg, v.vvt_ex_deg)
            overlap_scale = ve_model.overlap.residual_factor(d, rpm, v.p_man_kpa, v.p_exh_kpa)
        m_res, x_r = residual_fraction(
            v.p_exh_kpa, self.geo.vc_m3, m_air, m_fuel_cycle, overlap_scale
        )
        dt_evap = evaporative_cooling_k(m_fuel_cycle, m_air, fuel.h_fg_kj_kg, self.direct_injection)
        t_ivc = (m_air * v.t_man_k + m_res * T_RESIDUAL_K) / (m_air + m_res) - dt_evap
        t_wall = v.ect_c + K0 + WALL_ABOVE_ECT_K
        lam_in = (m_air / (m_fuel_cycle * afr)) if m_fuel_cycle > 0.0 else 0.0
        advance = cmd.ignition_advance_deg[idx]
        key, inp = quantize_inputs(
            rpm,
            m_air,
            min(lam_in, 9.0),
            x_r,
            t_ivc,
            advance,
            ivc_deg,
            evo_deg,
            t_wall,
            fire,
            self.fuel_index,
        )
        res: CycleResult = self.solver.solve(key, inp)
        # Escape: energia química que segue para o coletor e pós-combustão.
        oxygen = (
            (misfire and m_fuel_cycle > 0.0) or v.lambda_col_last > 1.0 or cmd.antilag_air_pct > 0.0
        )
        excess = 0.0
        if fire and lam is not None and lam < 1.0:
            excess = (res.m_fuel_kg - res.inputs.m_air_kg / afr) * fuel.lhv_mj_kg * 1e6
        ex = exhaust_event(
            res.t_evo_k,
            res.p_evo_pa / 1000.0,
            v.p_exh_kpa,
            m_air + m_fuel_cycle,
            res.unburned_chem_j,
            excess,
            oxygen,
            v.ect_c,
        )
        a = self.geo.crank_radius_m
        omega = rpm_to_rad_s(rpm)
        f_rod = (
            res.p_max_pa - 100_000.0
        ) * self.geo.piston_area_m2 - self.recip_kg * a * omega * omega * (1.0 + a / self.geo.rod_m)
        # Estado por cilindro e anel de trabalho.
        v.ve_last[idx] = ve
        v.m_air_last[idx] = m_air
        v.m_fuel_last[idx] = m_fuel_cycle
        v.lam_last[idx] = lam if (lam is not None and not fuel_cut) else math.nan
        v.adv_last[idx] = advance
        v.burn_last[idx] = res.burn_duration_deg
        v.pmax_last[idx] = res.p_max_pa / 1000.0
        v.thpk_last[idx] = res.theta_pmax_deg
        v.tumax_last[idx] = res.t_unburned_max_k
        v.frod_last[idx] = f_rod
        v.qwall_last[idx] = res.q_wall_j
        v.port_k_last[idx] = ex.t_port_k
        v.fire_last[idx] = 1.0 if fire else 0.0
        ri = v.ring_index
        v.ring_work_j[ri] = res.work_j
        v.ring_pmax_kpa[ri] = res.p_max_pa / 1000.0
        v.ring_index = (ri + 1) % self.n_cyl
        v.ring_count = min(v.ring_count + 1, self.n_cyl)
        v.m_trapped_cum_kg += m_air
        v.events_total += 1
        return _NEW_COMBUSTION_EVENT(
            cylinder=idx + 1,
            t_sim_s=t_ev,
            rpm=rpm,
            theta_start_deg=float(res.event_theta_start),
            pressure_kpa=list(res.event_pressure_kpa),
            t_unburned_k=list(res.event_t_unburned_k),
            burned_fraction=list(res.event_burned_fraction),
            p_max_kpa=res.p_max_pa / 1000.0,
            theta_pmax_deg_atdc=res.theta_pmax_deg,
            t_unburned_max_k=res.t_unburned_max_k,
            rod_force_peak_n=f_rod,
            imep_gross_kpa=imep_kpa(res.work_j, self.geo.vd_cyl_m3),
            lambda_real=None if fuel_cut else lam,
            fuel_octane_ron=fuel.ron,
            fuel_octane_mon=fuel.mon,
            misfire=misfire,
            afterfire_energy_j=ex.afterfire_energy_j,
            pop_event=ex.pop_event,
        )

    # ------------------------------------------------------------------ fecho do tick
    def _finish(  # noqa: PLR0915
        self,
        cmd: ActuatorCommands,
        load: DynoLoad,
        dt: float,
        flows: _Flows,
        events: list[CombustionEvent],
    ) -> EngineState:
        v = self.vars
        n = self.n_cyl
        geo = self.geo
        rpm = v.rpm
        running = rpm > 0.0 and not v.locked
        # Torque médio dos últimos n_cyl eventos (RF-03).
        if running and v.ring_count > 0:
            cnt = v.ring_count
            work = math.fsum(v.ring_work_j[:cnt]) / cnt if cnt < n else math.fsum(v.ring_work_j) / n
            pmax_mean = math.fsum(v.ring_pmax_kpa[:cnt]) / cnt
            imep = imep_kpa(work, geo.vd_cyl_m3)
        else:
            imep = 0.0
            pmax_mean = v.p_man_kpa
        sp = mean_piston_speed(geo.stroke_m, rpm)
        pmep = pmep_kpa(v.p_exh_kpa, v.p_man_kpa) if rpm > 0.0 else 0.0
        fmep = (
            chen_flynn_fmep_kpa(self.vehicle.engine.friction, pmax_mean, sp) if rpm > 0.0 else 0.0
        )
        omega = rpm_to_rad_s(rpm)
        sc_kw = flows.sc_power_kw if self.sc is not None else 0.0
        t_ind = imep * 1000.0 * geo.vd_total_m3 / (4.0 * math.pi)
        t_brake = brake_torque_nm(imep, pmep, fmep, geo.vd_total_m3, sc_kw, omega)
        p_kw = power_kw(t_brake, rpm)
        p_wheel = wheel_power_kw(
            p_kw, self.vehicle.drivetrain_efficiency, self.vehicle.drivetrain_fixed_loss_kw
        )
        # Combustível.
        fuel_rate = math.fsum(v.m_fuel_last) * rpm / 120.0 if running else 0.0
        v.fuel_rate_kg_s = fuel_rate
        demand_lph = None
        if fuel_rate > 0.0:
            dp_nom = self._rail_target(cmd.fuel_pump_duty_pct, None)
            scale = math.sqrt(max(dp_nom, 1.0) / max(v.rail_dp_kpa, 1.0))
            demand_lph = fuel_rate * scale / self.fuel.density_kg_m3 * 3.6e6
        v.rail_dp_kpa = first_order(
            v.rail_dp_kpa, self._rail_target(cmd.fuel_pump_duty_pct, demand_lph), dt, RAIL_TAU_S
        )
        # Dinâmica rotacional (RF-21) e bloqueio (RF-19).
        j_total = self.j_engine + load.reflected_inertia_kg_m2
        if v.locked:
            rpm_new = max(rpm - v.lock_rate_rpm_s * dt, 0.0)
        else:
            rpm_new = rpm + rpm_rate_per_s(t_brake - load.load_torque_crank_nm, j_total) * dt
            rpm_new = min(max(rpm_new, 0.0), self.max_rpm)
            if v.starter_s > 0.0:
                v.starter_s = max(v.starter_s - dt, 0.0)
                if rpm_new > STARTER_RELEASE_RPM:
                    v.starter_s = 0.0
                else:
                    rpm_new = max(rpm_new, STARTER_RPM)
            elif 0.0 < rpm_new < STALL_RPM:
                rpm_new = 0.0
                v.stalled = True
        if rpm_new <= 0.0:
            v.ring_count = 0
            v.ring_index = 0
            v.ring_work_j = [0.0] * n
            v.ring_pmax_kpa = [0.0] * n
        v.rpm = rpm_new
        # Temperaturas lumpadas (RF-24) e EGT por cilindro/coletor (RF-13).
        if self._thermal_kernel is not None:
            (
                v.ect_c,
                v.oil_c,
                v.egt_col_k,
                v.tc_col_c,
                v.egt_gas_k,
                v.tc_egt_c,
                v.piston_c,
                v.hot_spot_c,
                egt_probe,
            ) = self._thermal_kernel.step(
                running,
                rpm,
                dt,
                imep,
                v.t_amb_k,
                v.fan_m_s,
                v.ect_c,
                v.oil_c,
                v.egt_col_k,
                v.tc_col_c,
                v.qwall_last,
                v.m_air_last,
                v.m_fuel_last,
                v.port_k_last,
                v.fire_last,
                v.egt_gas_k,
                v.tc_egt_c,
                v.piston_c,
                v.hot_spot_c,
            )
        else:
            egt_probe = self._thermal_py(running, rpm, dt, imep)
        # Lambda do coletor e wideband (atraso de transporte + τ).
        fuel_sum = math.fsum(v.m_fuel_last)
        lam_col = (
            math.fsum(v.m_air_last) / (self.fuel.afr_stoich * fuel_sum)
            if (running and fuel_sum > 0.0)
            else None
        )
        v.lambda_col_last = lam_col if lam_col is not None else 2.0
        v.wb_index, v.wb_filtered = wideband_update(
            v.wb_buffer,
            v.wb_index,
            v.wb_filtered,
            v.lambda_col_last,
            rpm,
            dt,
            self.resolved.sim_hz,
            self.config.wideband_tau_s,
        )
        v.tick += 1
        # Montagem do EngineState (model_construct: sem custo de validação no hot path).
        fuel_g_s = fuel_rate * 1000.0
        lhv = self.fuel.lhv_mj_kg
        turbo_on = self.turbine is not None
        return _NEW_ENGINE_STATE(
            t_sim_s=v.tick / self.resolved.sim_hz,
            tick=v.tick,
            rpm=v.rpm,
            crank_angle_deg=v.theta_deg,
            locked=v.locked,
            stalled=v.stalled,
            map_kpa=v.p_man_kpa,
            boost_pre_throttle_kpa=v.p_boost_kpa if not self.pre_compressor else v.p_amb_kpa,
            exhaust_manifold_kpa=v.p_exh_kpa,
            t_manifold_c=v.t_man_k - K0,
            t_intercooler_out_c=(v.t_man_k - K0) if self.intercooler.spec is not None else None,
            ve_true=list(v.ve_last),
            m_air_mg=[m * 1e6 for m in v.m_air_last],
            m_fuel_mg=[m * 1e6 for m in v.m_fuel_last],
            lambda_cyl=[None if math.isnan(x) else x for x in v.lam_last],
            lambda_collector=lam_col,
            ignition_advance_deg=list(v.adv_last),
            burn_duration_deg=list(v.burn_last),
            p_max_kpa=list(v.pmax_last),
            theta_pmax_deg_atdc=list(v.thpk_last),
            t_unburned_max_k=list(v.tumax_last),
            rod_force_peak_n=list(v.frod_last),
            piston_temp_c=list(v.piston_c),
            hot_spot_temp_c=list(v.hot_spot_c),
            egt_c=[t - K0 for t in egt_probe],
            egt_collector_c=v.egt_col_k - K0,
            imep_gross_kpa=imep,
            pmep_kpa=pmep,
            fmep_kpa=fmep,
            torque_indicated_nm=t_ind,
            torque_nm=t_brake,
            power_kw=p_kw,
            wheel_power_kw=p_wheel,
            whp=p_wheel / 0.7457,
            fuel_flow_g_s=fuel_g_s,
            bsfc_g_kwh=(fuel_g_s * 3600.0 / p_kw) if p_kw > 1.0 else None,
            thermal_efficiency=(p_kw / (fuel_g_s * lhv)) if fuel_g_s > 0.0 else 0.0,
            turbo_rpm=rad_s_to_rpm(v.turbo_omega) if turbo_on else None,
            compressor_pressure_ratio=flows.pr_comp if self.induction != "natural" else None,
            compressor_efficiency=flows.eta_comp if self.induction != "natural" else None,
            surge_margin=flows.surge_margin if turbo_on else None,
            wastegate_position_pct=v.wastegate_x * 100.0 if turbo_on else None,
            supercharger_rpm=flows.sc_rpm if self.sc is not None else None,
            supercharger_power_kw=sc_kw if self.sc is not None else None,
            ect_c=v.ect_c,
            iat_c=v.t_man_k - K0,
            events=events,
            real_time_factor=None,
        )

    def _thermal_py(self, running: bool, rpm: float, dt: float, imep: float) -> list[float]:
        """Referência Python do fecho térmico (``ThermalKernel`` em Rust)."""
        v = self.vars
        n = self.n_cyl
        # Temperaturas lumpadas (RF-24).
        cyc_hz = rpm / 120.0 if running else 0.0
        q_wall = [max(q, 0.0) * cyc_hz for q in v.qwall_last]
        v.ect_c += dt * self.coolant.rate(v.ect_c, math.fsum(q_wall), v.t_amb_k - K0, v.fan_m_s)
        load_frac = imep / LOAD_REF_KPA if running else 0.0
        v.oil_c += dt * oil_temp_rate(v.oil_c, v.ect_c, load_frac)
        # EGT por cilindro, coletor e termopares (RF-13).
        tau_tc = self.config.egt_thermocouple_tau_s
        egt_gas = v.egt_gas_k
        cool_target = v.ect_c + K0
        m_ex = [v.m_air_last[i] + v.m_fuel_last[i] for i in range(n)]
        # EGT exposta por cilindro (egt_c e termopares) no ponto da sonda do runner: perda de
        # calor do coletor (mesmo modelo e UA) no 1.º quarto do runner, com o caudal do
        # cilindro. Em plena carga tira 10–20 K; em marcha lenta/carga baixa o caudal é
        # ínfimo e a temperatura tende à parede (sem isto a porta mostrava 1100 °C a 870 rpm).
        # O ponto quente (pré-ignição) segue a mesma temperatura.
        ua_probe = self.exh_ua_w_k * EGT_PROBE_UA_FRACTION / n
        cyc_flow = rpm / 120.0 if running else 0.0
        egt_probe = [0.0] * n
        for i in range(n):
            if running:
                egt_gas[i] = first_order(egt_gas[i], v.port_k_last[i], dt, CYLINDER_GAS_TAU_S)
                egt_probe[i] = manifold_heat_loss(egt_gas[i], m_ex[i] * cyc_flow, ua_probe, v.ect_c)
            else:
                egt_gas[i] = first_order(egt_gas[i], cool_target, dt, 5.0)
                egt_probe[i] = egt_gas[i]
            v.tc_egt_c[i] = first_order(v.tc_egt_c[i], egt_probe[i] - K0, dt, tau_tc)
            firing = running and v.fire_last[i] > 0.0
            v.piston_c[i] = relax(
                v.piston_c[i], piston_target_c(v.ect_c, q_wall[i]), dt, PISTON_TAU_S
            )
            v.hot_spot_c[i] = relax(
                v.hot_spot_c[i],
                hot_spot_target_c(v.ect_c, egt_probe[i] - K0, firing),
                dt,
                HOT_SPOT_TAU_S,
            )
        m_tot = math.fsum(m_ex)
        col_target = (
            (math.fsum(m_ex[i] * egt_gas[i] for i in range(n)) / m_tot)
            if m_tot > 0.0
            else math.fsum(egt_gas) / n
        )
        if running:
            col_target = manifold_heat_loss(
                col_target, m_tot * rpm / 120.0, self.exh_ua_w_k, v.ect_c
            )
            if self.egt_backpressure_factor != 1.0:
                t_wall = v.ect_c + K0 + EXH_MANIFOLD_WALL_ABOVE_ECT_K
                col_target = t_wall + (col_target - t_wall) * self.egt_backpressure_factor
        v.egt_col_k = first_order(v.egt_col_k, col_target, dt, COLLECTOR_TAU_S)
        v.tc_col_c = first_order(v.tc_col_c, v.egt_col_k - K0, dt, tau_tc)
        return egt_probe

    def _check_divergence(self) -> None:
        v = self.vars
        checks = (
            ("rpm", v.rpm, 0.0, 1e5),
            ("p_man_kpa", v.p_man_kpa, 0.0, 1e4),
            ("p_boost_kpa", v.p_boost_kpa, 0.0, 1e4),
            ("p_exh_kpa", v.p_exh_kpa, 0.0, 1e4),
            ("egt_col_k", v.egt_col_k, 0.0, T_DIVERGENCE_K),
            ("t_man_k", v.t_man_k, 0.0, T_DIVERGENCE_K),
            ("turbo_omega", v.turbo_omega, 0.0, 1e6),
            ("ect_c", v.ect_c, -K0, T_DIVERGENCE_K),
        )
        for name, value, lo, hi in checks:
            if not (math.isfinite(value) and lo <= value <= hi):
                raise PhysicsError(
                    PHYSICS_NUMERIC_DIVERGENCE,
                    f"variável '{name}' divergiu ({value!r}) no tick {v.tick}",
                    variable=name,
                    tick=v.tick,
                )
        for t in v.egt_gas_k:
            if not (math.isfinite(t) and 0.0 < t < T_DIVERGENCE_K):
                raise PhysicsError(
                    PHYSICS_NUMERIC_DIVERGENCE,
                    f"variável 'egt_gas_k' divergiu ({t!r}) no tick {v.tick}",
                    variable="egt_gas_k",
                    tick=v.tick,
                )


def _backpressure(config: PhysicsConfig) -> tuple[float, float]:
    """``(Δp do escape a ṁ_ref em kPa, fator do excesso de EGT do coletor)`` do downpipe."""
    scale = config.exhaust_backpressure_scale
    return EXHAUST_BACKPRESSURE_KPA * scale, 1.0 - DOWNPIPE_EGT_GAIN * (1.0 - scale)


def _flex_ethanol_pct(fuel: FuelSpec, ethanol_pct: float | None) -> float | None:
    """Teor do sensor flex: obrigatório com ``fuel_id = "flex"`` e ignorado nos outros."""
    if fuel.fuel_id != FLEX_FUEL_ID:
        return None
    if ethanol_pct is None or not 0.0 <= ethanol_pct <= 100.0:  # noqa: PLR2004
        raise PhysicsError(
            PHYSICS_CONFIG_INVALID, "combustível flex exige ethanol_pct entre 0 e 100 %"
        )
    return ethanol_pct
