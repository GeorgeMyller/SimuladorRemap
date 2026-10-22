"""Stubs da extensão nativa. Cada trilha acrescenta as assinaturas do seu submódulo."""

from types import ModuleType

__version__: str

# --- tables (trilha RA, feature 003: T008/T009) ------------------------------------
class _TableSet:
    """Grupo de tabelas avaliado em lote: specs ``(qx, qy|-1, xs, ys, values)``."""

    def __init__(
        self, specs: list[tuple[int, int, list[float], list[float], list[list[float]]]]
    ) -> None: ...
    def eval(self, inputs: list[float]) -> list[float]: ...
    def __len__(self) -> int: ...

class _BoostPid:
    integ: float
    map_filt: float
    map_filt_prev: float
    @property
    def duty(self) -> float: ...
    @property
    def target_kpa(self) -> float: ...
    @property
    def pid_active(self) -> bool: ...
    def __init__(
        self,
        enabled: bool,
        closed_loop: bool,
        kp: float,
        ki: float,
        kd: float,
        d_tau: float,
        window: float,
        integ_limit: float,
    ) -> None: ...
    def configure(
        self,
        enabled: bool,
        closed_loop: bool,
        kp: float,
        ki: float,
        kd: float,
        d_tau: float,
        window: float,
        integ_limit: float,
    ) -> None: ...
    def step(
        self, map_kpa: float, target: float, dt: float, base_duty: float, boost_cut: bool
    ) -> float: ...

class _VvtRate:
    intake_deg: float
    exhaust_deg: float
    def __init__(
        self,
        enabled: bool,
        min_ect_c: float,
        intake_offset: float,
        exhaust_offset: float,
        max_rate: float,
    ) -> None: ...
    def configure(
        self,
        enabled: bool,
        min_ect_c: float,
        intake_offset: float,
        exhaust_offset: float,
        max_rate: float,
    ) -> None: ...
    def targets(
        self, ect_c: float, dt: float, intake: float, exhaust: float
    ) -> tuple[float, float]: ...

class _OverrunFsm:
    @property
    def state(self) -> str: ...
    @property
    def closed_since(self) -> float: ...
    @property
    def protected(self) -> bool: ...
    @property
    def effective_intensity_pct(self) -> float: ...
    @property
    def effective_duration_s(self) -> float: ...
    @property
    def window_s(self) -> float: ...
    def __init__(
        self,
        enabled: bool,
        dfco_enabled: bool,
        dfco_tps_max: float,
        dfco_rpm_min: float,
        dfco_resume_rpm: float,
        dfco_delay_s: float,
        pops_enabled: bool,
        pops_rpm_min: float,
        pops_rpm_max: float,
        pops_tps_max: float,
        fuel_cut_delay_s: float,
        intensity_pct: float,
        max_duration_s: float,
        egt_turbine_max_c: float,
        catalyst_present: bool,
        catalyst_max_intensity_pct: float,
        catalyst_max_duration_s: float,
        n_cyl: int,
    ) -> None: ...
    def update(self, t: float, rpm: float, tps: float, egt_c: float) -> tuple[int, bool, int]: ...

class _TwoStepFsm:
    @property
    def active(self) -> bool: ...
    @property
    def active_since(self) -> float: ...
    @property
    def locked_out(self) -> bool: ...
    @property
    def cutting(self) -> bool: ...
    @property
    def released_t(self) -> float: ...
    @property
    def ramp_from(self) -> float: ...
    def __init__(
        self,
        enabled: bool,
        target_rpm: float,
        rolling: bool,
        ign_advance_deg: float,
        by_clutch: bool,
        max_speed_kmh: float,
        min_tps_pct: float,
        max_active_s: float,
        release_ramp_s: float,
    ) -> None: ...
    def update(
        self,
        t: float,
        rpm: float,
        tps: float,
        speed_kmh: float,
        clutch: bool,
        launch: bool,
        adv_ref: float,
        n_cyl: int,
    ) -> tuple[bool, int, float, float]: ...

class _TablesModule(ModuleType):
    TableSet: type[_TableSet]
    BoostPid: type[_BoostPid]
    VvtRate: type[_VvtRate]
    OverrunFsm: type[_OverrunFsm]
    TwoStepFsm: type[_TwoStepFsm]
    @staticmethod
    def interp1(xs: list[float], vs: list[float], x: float) -> float: ...
    @staticmethod
    def interp2(
        xs: list[float], ys: list[float], z: list[list[float]], x: float, y: float
    ) -> float: ...
    @staticmethod
    def flex_factors(
        ethanol_pct: float,
        afr_stoich: float,
        fuel_density_g_cc: float,
        afr_e27: float,
        afr_e100: float,
        density_e27: float,
        density_e100: float,
    ) -> tuple[float, float]: ...

tables: _TablesModule

# --- fim tables ------------------------------------------------------------------------
# --- cycle (trilha RB, feature 003: T010/T011) -------------------------------------
class _CycleKernel:
    """Ciclo fechado IVC → EVO; ``solve`` devolve os campos de ``CycleResult`` após ``inputs``."""

    def __init__(
        self,
        volume: list[float],
        dvol: list[float],
        wall_area: list[float],
        stroke_m: float,
        vd_cyl_m3: float,
        woschni_k: float,
        wiebe_a: float,
        wiebe_m: float,
        duration_ref_deg: float,
        rpm_ref: float,
    ) -> None: ...
    def solve(
        self,
        rpm: float,
        m_air_kg: float,
        lam: float,
        x_r: float,
        t_ivc_k: float,
        advance_deg: float,
        ivc_deg: int,
        evo_deg: int,
        t_wall_k: float,
        fire: bool,
        afr: float,
        lhv_j_kg: float,
        b_m: float,
        b_phi: float,
        phi_m: float,
    ) -> tuple[object, ...]: ...

class _GasKernel:
    """Um tick do bloco de gás; ``state`` segue ``physics.kernels.GAS_STATE_FIELDS``."""

    def __init__(self, config: dict[str, object]) -> None: ...
    def ve(
        self, rpm: float, map_kpa: float, p_exh_kpa: float, vvt_deg: float, vvt_ex_deg: float
    ) -> float: ...
    def step(
        self, state: list[float], bypass_open: bool, antilag_air_pct: float, leak: float
    ) -> tuple[float, ...]: ...

class _ThermalKernel:
    def __init__(
        self, n_cyl: int, exh_ua_w_k: float, egt_backpressure_factor: float, tau_tc: float
    ) -> None: ...
    def step(
        self,
        running: bool,
        rpm: float,
        dt: float,
        imep: float,
        t_amb_k: float,
        fan_m_s: float,
        ect_c: float,
        oil_c: float,
        egt_col_k: float,
        tc_col_c: float,
        qwall_last: list[float],
        m_air_last: list[float],
        m_fuel_last: list[float],
        port_k_last: list[float],
        fire_last: list[float],
        egt_gas_k: list[float],
        tc_egt_c: list[float],
        piston_c: list[float],
        hot_spot_c: list[float],
    ) -> tuple[
        float,
        float,
        float,
        float,
        list[float],
        list[float],
        list[float],
        list[float],
        list[float],
    ]: ...

class _CycleModule(ModuleType):
    CycleKernel: type[_CycleKernel]
    GasKernel: type[_GasKernel]
    ThermalKernel: type[_ThermalKernel]
    GAS_STATE_LEN: int
    @staticmethod
    def gamma_of_t(t_k: float) -> float: ...
    @staticmethod
    def internal_energy_per_kg(t_k: float) -> float: ...
    @staticmethod
    def fsum(values: list[float]) -> float: ...
    @staticmethod
    def burn_duration_deg(
        rpm: float,
        lam: float,
        b_m: float,
        b_phi: float,
        phi_m: float,
        x_r: float,
        t_u_k: float,
        p_kpa: float,
        duration_ref_deg: float = 55.0,
        rpm_ref: float = 3000.0,
    ) -> float: ...

cycle: _CycleModule

# --- fim cycle -------------------------------------------------------------------------
# --- damage (trilha RC, feature 003: T012) -----------------------------------------
class _DamageKernel:
    """Passo contínuo do ``DamageModel`` ligado (sem cópia) aos seus arrays float64."""

    n_cyl: int
    def __init__(
        self,
        *,
        health: object,
        virtual_health: object,
        causes: object,
        first_damage: object,
        knock_temp: object,
        last_intensity: object,
        valve_temp: object,
        turbine_temp: object,
        n_cyl: int,
        has_turbine: bool,
        enabled: bool,
        thermal: bool,
        mechanical: bool,
        knock_temp_gain_c: float,
        knock_temp_tau_s: float,
        lean_map_min_kpa: float,
        k_lean_c: float,
        lambda_lean_ref: float,
        lm_constant: float,
        piston_limit_c: float,
        piston_t_ref_s: float,
        valve_limit_c: float,
        valve_t_ref_s: float,
        valve_tau_s: float,
        turbine_limit_c: float,
        turbine_t_ref_s: float,
        turbine_tau_s: float,
        max_rpm: float,
        bearing_overrev_rate: float,
        turbo_max_rpm: float | None,
        turbo_burst_ratio: float,
        turbo_overspeed_rate: float,
    ) -> None: ...
    def continuous(
        self,
        piston_temp_c: list[float],
        lambda_cyl: list[float | None],
        egt_c: list[float],
        map_kpa: float,
        egt_collector_c: float,
        rpm: float,
        turbo_rpm: float | None,
        t: float,
        dt: float,
    ) -> tuple[list[float], list[int], bool]: ...

class _DamageModule(ModuleType):
    DamageKernel: type[_DamageKernel]
    @staticmethod
    def knock_onset(
        pressure_kpa: list[float],
        t_unburned_k: list[float],
        rpm: float,
        octane: float,
        tau_multiplier: float,
        tau_min_temp_k: float,
        tau_min_pressure_kpa: float,
        tau_saturation_ms: float,
    ) -> tuple[float, int]: ...
    @staticmethod
    def traces_finite(a: list[float], b: list[float], c: list[float]) -> bool: ...

damage: _DamageModule
# --- fim damage ------------------------------------------------------------------------
