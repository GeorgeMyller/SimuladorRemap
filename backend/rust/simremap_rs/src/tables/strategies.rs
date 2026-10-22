//! Estratégias da ECU com estado: PID de boost, came (limite de taxa), overrun,
//! two-step e fatores flex.
//!
//! Cada classe espelha a máquina de estados do módulo Python correspondente em
//! `simremap.ecu.strategies` com a mesma ordem das operações; `min`/`max` seguem a regra
//! do Python (devolve o primeiro argumento quando a comparação é falsa, inclusive NaN).
//! Os pedidos à arbitragem e os eventos continuam do lado Python: o `step` devolve só
//! os números necessários para os escrever.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const TOL: f64 = 1e-9;
const BAND_RPM: f64 = 50.0;

/// `min(a, b)` do Python.
#[inline]
fn py_min(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

/// `max(a, b)` do Python.
#[inline]
fn py_max(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// `round(x)` do Python para `float` → `int` (empate para o par).
#[inline]
fn py_round(x: f64) -> i64 {
    x.round_ties_even() as i64
}

// --------------------------------------------------------------------------- boost

/// Filtro da derivada e PID da wastegate (`BoostControl.compute_duty`).
#[pyclass(module = "simremap_rs._native.tables")]
pub struct BoostPid {
    enabled: bool,
    closed_loop: bool,
    kp: f64,
    ki: f64,
    kd: f64,
    d_tau: f64,
    window: f64,
    integ_limit: f64,
    #[pyo3(get, set)]
    integ: f64,
    #[pyo3(get, set)]
    map_filt: f64,
    #[pyo3(get, set)]
    map_filt_prev: f64,
    #[pyo3(get)]
    duty: f64,
    #[pyo3(get)]
    target_kpa: f64,
    #[pyo3(get)]
    pid_active: bool,
}

#[pymethods]
impl BoostPid {
    #[new]
    #[pyo3(signature = (enabled, closed_loop, kp, ki, kd, d_tau, window, integ_limit))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        enabled: bool,
        closed_loop: bool,
        kp: f64,
        ki: f64,
        kd: f64,
        d_tau: f64,
        window: f64,
        integ_limit: f64,
    ) -> Self {
        Self {
            enabled,
            closed_loop,
            kp,
            ki,
            kd,
            d_tau,
            window,
            integ_limit,
            integ: 0.0,
            map_filt: -1.0,
            map_filt_prev: -1.0,
            duty: 0.0,
            target_kpa: 0.0,
            pid_active: false,
        }
    }

    /// Nova configuração; o estado (integrador, filtro) continua.
    #[pyo3(signature = (enabled, closed_loop, kp, ki, kd, d_tau, window, integ_limit))]
    #[allow(clippy::too_many_arguments)]
    fn configure(
        &mut self,
        enabled: bool,
        closed_loop: bool,
        kp: f64,
        ki: f64,
        kd: f64,
        d_tau: f64,
        window: f64,
        integ_limit: f64,
    ) {
        self.enabled = enabled;
        self.closed_loop = closed_loop;
        self.kp = kp;
        self.ki = ki;
        self.kd = kd;
        self.d_tau = d_tau;
        self.window = window;
        self.integ_limit = integ_limit;
    }

    /// Duty da wastegate (%) com o alvo final e o duty base já lido da tabela.
    fn step(&mut self, map_kpa: f64, target: f64, dt: f64, base_duty: f64, boost_cut: bool) -> f64 {
        self.target_kpa = target;
        if self.map_filt < 0.0 {
            self.map_filt = map_kpa;
            self.map_filt_prev = map_kpa;
        }
        self.map_filt_prev = self.map_filt;
        self.map_filt += (map_kpa - self.map_filt) * dt / (self.d_tau + dt);
        if !self.enabled || boost_cut {
            self.pid_active = false;
            self.duty = 0.0;
            return 0.0;
        }
        let mut duty = base_duty;
        self.pid_active = false;
        if self.closed_loop && map_kpa >= target - self.window {
            self.pid_active = true;
            let e = target - map_kpa;
            let integ = self.integ + self.ki * e * dt;
            let lim = self.integ_limit;
            self.integ = if integ > lim {
                lim
            } else if integ < -lim {
                -lim
            } else {
                integ
            };
            let d = -self.kd * (self.map_filt - self.map_filt_prev) / dt;
            duty += self.kp * e + self.integ + d;
        }
        self.duty = if duty < 0.0 {
            0.0
        } else if duty > 100.0 {
            100.0
        } else {
            duty
        };
        self.duty
    }
}

// --------------------------------------------------------------------------- came

#[inline]
fn slew(current: f64, target: f64, step: f64) -> f64 {
    current + py_min(py_max(target - current, -step), step)
}

/// Alvos de came com inibição a frio, offsets e limite de taxa (`VvtControl.targets`).
#[pyclass(module = "simremap_rs._native.tables")]
pub struct VvtRate {
    enabled: bool,
    min_ect_c: f64,
    intake_offset: f64,
    exhaust_offset: f64,
    max_rate: f64,
    #[pyo3(get, set)]
    intake_deg: f64,
    #[pyo3(get, set)]
    exhaust_deg: f64,
}

#[pymethods]
impl VvtRate {
    #[new]
    fn new(enabled: bool, min_ect_c: f64, intake_offset: f64, exhaust_offset: f64, max_rate: f64) -> Self {
        Self {
            enabled,
            min_ect_c,
            intake_offset,
            exhaust_offset,
            max_rate,
            intake_deg: 0.0,
            exhaust_deg: 0.0,
        }
    }

    fn configure(&mut self, enabled: bool, min_ect_c: f64, intake_offset: f64, exhaust_offset: f64, max_rate: f64) {
        self.enabled = enabled;
        self.min_ect_c = min_ect_c;
        self.intake_offset = intake_offset;
        self.exhaust_offset = exhaust_offset;
        self.max_rate = max_rate;
    }

    fn targets(&mut self, ect_c: f64, dt: f64, intake: f64, exhaust: f64) -> (f64, f64) {
        if !self.enabled {
            self.intake_deg = intake;
            self.exhaust_deg = exhaust;
            return (intake, exhaust);
        }
        let (mut i, mut e) = (intake, exhaust);
        if ect_c < self.min_ect_c {
            i = 0.0;
            e = 0.0;
        } else {
            i += self.intake_offset;
            e += self.exhaust_offset;
        }
        let step = self.max_rate * dt;
        self.intake_deg = slew(self.intake_deg, i, step);
        self.exhaust_deg = slew(self.exhaust_deg, e, step);
        (self.intake_deg, self.exhaust_deg)
    }
}

// --------------------------------------------------------------------------- overrun

const IDLE: u8 = 0;
const POPS: u8 = 1;
const CUT: u8 = 2;

/// DFCO e pops & bangs com proteção (`Overrun.update`).
#[pyclass(module = "simremap_rs._native.tables")]
pub struct OverrunFsm {
    enabled: bool,
    dfco_enabled: bool,
    dfco_tps_max: f64,
    dfco_rpm_min: f64,
    dfco_resume_rpm: f64,
    dfco_delay_s: f64,
    pops_enabled: bool,
    pops_rpm_min: f64,
    pops_rpm_max: f64,
    pops_tps_max: f64,
    egt_turbine_max_c: f64,
    n_cyl: i64,
    #[pyo3(get)]
    effective_intensity_pct: f64,
    #[pyo3(get)]
    effective_duration_s: f64,
    #[pyo3(get)]
    window_s: f64,
    state: u8,
    #[pyo3(get)]
    closed_since: f64,
    #[pyo3(get)]
    protected: bool,
}

#[pymethods]
impl OverrunFsm {
    #[new]
    #[pyo3(signature = (
        enabled, dfco_enabled, dfco_tps_max, dfco_rpm_min, dfco_resume_rpm, dfco_delay_s,
        pops_enabled, pops_rpm_min, pops_rpm_max, pops_tps_max, fuel_cut_delay_s,
        intensity_pct, max_duration_s, egt_turbine_max_c, catalyst_present,
        catalyst_max_intensity_pct, catalyst_max_duration_s, n_cyl
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        enabled: bool,
        dfco_enabled: bool,
        dfco_tps_max: f64,
        dfco_rpm_min: f64,
        dfco_resume_rpm: f64,
        dfco_delay_s: f64,
        pops_enabled: bool,
        pops_rpm_min: f64,
        pops_rpm_max: f64,
        pops_tps_max: f64,
        fuel_cut_delay_s: f64,
        intensity_pct: f64,
        max_duration_s: f64,
        egt_turbine_max_c: f64,
        catalyst_present: bool,
        catalyst_max_intensity_pct: f64,
        catalyst_max_duration_s: f64,
        n_cyl: i64,
    ) -> Self {
        let mut intensity = intensity_pct;
        let mut duration = max_duration_s;
        if catalyst_present {
            intensity = py_min(intensity, catalyst_max_intensity_pct);
            duration = py_min(duration, catalyst_max_duration_s);
        }
        Self {
            enabled,
            dfco_enabled,
            dfco_tps_max,
            dfco_rpm_min,
            dfco_resume_rpm,
            dfco_delay_s,
            pops_enabled,
            pops_rpm_min,
            pops_rpm_max,
            pops_tps_max,
            egt_turbine_max_c,
            n_cyl,
            effective_intensity_pct: intensity,
            effective_duration_s: duration,
            window_s: py_min(fuel_cut_delay_s, duration),
            state: IDLE,
            closed_since: f64::INFINITY,
            protected: false,
        }
    }

    #[getter]
    fn state(&self) -> &'static str {
        match self.state {
            POPS => "pops",
            CUT => "cut",
            _ => "idle",
        }
    }

    /// Passo: `(estado, proteção emitida, cilindros em corte no padrão de pops)`.
    ///
    /// Estado 0 = idle, 1 = pops, 2 = cut. Desligada devolve `(0, False, 0)`.
    fn update(&mut self, t: f64, rpm: f64, tps: f64, egt_c: f64) -> (u8, bool, i64) {
        if !self.enabled {
            self.state = IDLE;
            return (IDLE, false, 0);
        }
        let closed_max = py_max(
            if self.pops_enabled { self.pops_tps_max } else { 0.0 },
            self.dfco_tps_max,
        );
        if tps > closed_max {
            self.state = IDLE;
            self.closed_since = f64::INFINITY;
            self.protected = false;
            return (IDLE, false, 0);
        }
        if self.closed_since == f64::INFINITY {
            self.closed_since = t;
        }
        let elapsed = t - self.closed_since;
        let mut pops_ok = self.pops_enabled
            && !self.protected
            && tps <= self.pops_tps_max
            && self.pops_rpm_min <= rpm
            && rpm <= self.pops_rpm_max;
        let mut protect = false;
        if pops_ok && egt_c >= self.egt_turbine_max_c {
            self.protected = true;
            pops_ok = false;
            protect = true;
        }
        if self.state == CUT {
            if rpm < self.dfco_resume_rpm {
                self.state = IDLE;
            }
        } else if pops_ok && elapsed < self.window_s {
            self.state = POPS;
        } else if self.state == POPS && pops_ok && rpm >= self.dfco_resume_rpm {
            self.state = CUT;
        } else {
            self.state = IDLE;
            if self.dfco_enabled
                && tps <= self.dfco_tps_max
                && rpm >= self.dfco_rpm_min
                && elapsed >= self.dfco_delay_s - TOL
            {
                self.state = CUT;
            }
        }
        let mut n_cut = 0;
        if self.state == POPS {
            let n = self.n_cyl;
            let firing = py_round(self.effective_intensity_pct / 100.0 * n as f64);
            n_cut = n - firing;
        }
        (self.state, protect, n_cut)
    }
}

// --------------------------------------------------------------------------- two-step

/// Launch control (`TwoStep.update`).
#[pyclass(module = "simremap_rs._native.tables")]
pub struct TwoStepFsm {
    enabled: bool,
    target_rpm: f64,
    rolling: bool,
    ign_advance_deg: f64,
    by_clutch: bool,
    max_speed_kmh: f64,
    min_tps_pct: f64,
    max_active_s: f64,
    release_ramp_s: f64,
    #[pyo3(get)]
    active: bool,
    #[pyo3(get)]
    active_since: f64,
    #[pyo3(get)]
    locked_out: bool,
    #[pyo3(get)]
    cutting: bool,
    #[pyo3(get)]
    released_t: f64,
    #[pyo3(get)]
    ramp_from: f64,
}

#[pymethods]
impl TwoStepFsm {
    #[new]
    #[pyo3(signature = (
        enabled, target_rpm, rolling, ign_advance_deg, by_clutch, max_speed_kmh,
        min_tps_pct, max_active_s, release_ramp_s
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        enabled: bool,
        target_rpm: f64,
        rolling: bool,
        ign_advance_deg: f64,
        by_clutch: bool,
        max_speed_kmh: f64,
        min_tps_pct: f64,
        max_active_s: f64,
        release_ramp_s: f64,
    ) -> Self {
        Self {
            enabled,
            target_rpm,
            rolling,
            ign_advance_deg,
            by_clutch,
            max_speed_kmh,
            min_tps_pct,
            max_active_s,
            release_ramp_s,
            active: false,
            active_since: f64::INFINITY,
            locked_out: false,
            cutting: false,
            released_t: f64::NEG_INFINITY,
            ramp_from: 0.0,
        }
    }

    /// Passo: `(ativo, cilindros em corte, retardo da rampa, duração no timeout)`.
    ///
    /// Com `rolling_cut` o número de cortes é o do padrão rotativo; nos outros modos vale
    /// `n_cyl` em corte total e 0 sem corte. Retardo e timeout valem NaN quando ausentes.
    #[allow(clippy::too_many_arguments)]
    fn update(
        &mut self,
        t: f64,
        rpm: f64,
        tps: f64,
        speed_kmh: f64,
        clutch: bool,
        launch: bool,
        adv_ref: f64,
        n_cyl: i64,
    ) -> (bool, i64, f64, f64) {
        let nan = f64::NAN;
        if !self.enabled {
            return (false, 0, nan, nan);
        }
        let trigger = if self.by_clutch { clutch } else { launch };
        let cond = trigger && tps >= self.min_tps_pct && speed_kmh <= self.max_speed_kmh;
        if !cond {
            self.locked_out = false;
        }
        let mut timeout = nan;
        if self.active && (!cond || t - self.active_since >= self.max_active_s - TOL) {
            if cond {
                self.locked_out = true;
                timeout = t - self.active_since;
            }
            self.active = false;
            self.cutting = false;
            self.released_t = t;
            self.ramp_from = py_max(0.0, adv_ref - self.ign_advance_deg);
        } else if !self.active && cond && !self.locked_out {
            self.active = true;
            self.active_since = t;
        }
        if self.active {
            let n_cut = if self.rolling {
                let f = (rpm - self.target_rpm + BAND_RPM) / (2.0 * BAND_RPM);
                let f = if f < 0.0 {
                    0.0
                } else if f > 1.0 {
                    1.0
                } else {
                    f
                };
                py_round(f * n_cyl as f64)
            } else {
                self.cutting = if self.cutting {
                    rpm >= self.target_rpm - BAND_RPM
                } else {
                    rpm >= self.target_rpm
                };
                if self.cutting {
                    n_cyl
                } else {
                    0
                }
            };
            return (true, n_cut, nan, timeout);
        }
        if self.release_ramp_s > 0.0 && self.ramp_from > 0.0 {
            let u = (t - self.released_t) / self.release_ramp_s;
            if u < 1.0 {
                return (false, 0, self.ramp_from * (1.0 - u), timeout);
            }
        }
        (false, 0, nan, timeout)
    }
}

// --------------------------------------------------------------------------- flex

const E_MIN: f64 = 27.0;
const E_MAX: f64 = 100.0;

fn blend_weight(ethanol_pct: f64) -> PyResult<f64> {
    let e = py_min(py_max(ethanol_pct, E_MIN), E_MAX);
    if !(E_MIN <= e && e <= E_MAX) {
        return Err(PyValueError::new_err(format!(
            "ethanol_pct {ethanol_pct} fora de 27–100 %"
        )));
    }
    Ok((e - E_MIN) / (E_MAX - E_MIN))
}

/// Fatores flex `(massa, abertura)` do `EcuRuntime._flex_corrections`.
///
/// `massa = AFR_hw / AFR_blend(etanol)`; `abertura = massa · ρ_hw / ρ_blend(etanol)`.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn flex_factors(
    ethanol_pct: f64,
    afr_stoich: f64,
    fuel_density_g_cc: f64,
    afr_e27: f64,
    afr_e100: f64,
    density_e27: f64,
    density_e100: f64,
) -> PyResult<(f64, f64)> {
    let t = blend_weight(ethanol_pct)?;
    let afr = 1.0 / ((1.0 - t) / afr_e27 + t / afr_e100);
    let mass = afr_stoich / afr;
    let t = blend_weight(ethanol_pct)?;
    let rho = density_e27 + (density_e100 - density_e27) * t;
    Ok((mass, mass * fuel_density_g_cc / rho))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<BoostPid>()?;
    m.add_class::<VvtRate>()?;
    m.add_class::<OverrunFsm>()?;
    m.add_class::<TwoStepFsm>()?;
    m.add_function(wrap_pyfunction!(flex_factors, m)?)?;
    Ok(())
}
