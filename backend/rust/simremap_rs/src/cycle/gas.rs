//! Volumes de gás, VE física, compressor/turbina, supercharger e intercooler por tick.
//!
//! Espelho de `PhysicsEngine._gas` + `_flows` (e de `manifold`, `turbo`, `supercharger`,
//! `fuel.TrueVolumetricEfficiency`/`ValveOverlap`). Um tick inteiro (todos os subpassos,
//! Jacobiano por diferenças finitas e eliminação de Gauss) corre numa só chamada.

use super::interp::{bisect_right, pw2, py_max, py_min, Interp1, Interp2};
use std::f64::consts::PI;

pub const R_AIR: f64 = 287.05;
const GAMMA_AIR: f64 = 1.40;
const CD_THROTTLE: f64 = 0.85;
const IDLE_AREA_FRACTION: f64 = 0.004;
const PR_LINEAR: f64 = 0.98;
const FD_STEP_KPA: f64 = 0.01;
const VE_MIN: f64 = 0.20;
const VE_MAX: f64 = 1.35;
const OVERLAP_SCALE_DEG: f64 = 40.0;
const K_OVERLAP_VE: f64 = 0.08;
const OVERLAP_RPM_CROSS: f64 = 3500.0;
const OVERLAP_RPM_WIDTH: f64 = 1000.0;
const SCAVENGE_DP_KPA: f64 = 20.0;
const CP_AIR: f64 = 1005.0;
const CP_EXH: f64 = 1200.0;
const GAMMA_EXH: f64 = 1.33;
const R_EXH: f64 = 287.0;
const ETA_C_MIN: f64 = 0.45;
const SURGE_FLOW_FRACTION: f64 = 0.30;
const SURGE_PR_MIN: f64 = 1.05;
const SPEED_LINE_LINEAR: f64 = 0.98;
const T_REF_K: f64 = 298.15;
const P_REF_KPA: f64 = 101.325;
const OMEGA_FLOOR: f64 = 500.0;
const OVERSPEED_LINE_CAP: f64 = 1.05;
const OVERSPEED_ETA_SLOPE: f64 = 4.0;
const OVERSPEED_ETA_FLOOR: f64 = 0.2;
const ETA_V_MIN: f64 = 0.5;
const ETA_V_MAX: f64 = 0.98;
const BYPASS_AREA_M2: f64 = 40e-4;
const BOV_AREA_M2: f64 = 5e-4;
const ANTILAG_AREA_M2: f64 = 2e-4;
const IC_CAPACITY_J_K: f64 = 12000.0;
const IC_HA_BASE_W_K: f64 = 150.0;
const IC_HA_FAN_W_K_PER_M_S: f64 = 40.0;

// ------------------------------------------------------------------ primitivas (manifold)
fn psi_raw(pr: f64, gamma: f64) -> f64 {
    let crit = (2.0 / (gamma + 1.0)).powf(gamma / (gamma - 1.0));
    if pr <= crit {
        let expo = (gamma + 1.0) / (2.0 * (gamma - 1.0));
        return gamma.sqrt() * (2.0 / (gamma + 1.0)).powf(expo);
    }
    let val = pr.powf(2.0 / gamma) - pr.powf((gamma + 1.0) / gamma);
    (2.0 * gamma / (gamma - 1.0) * py_max(val, 0.0)).sqrt()
}

#[derive(Clone, Copy, Debug)]
struct Psi {
    lin_air: f64,
    lin_exh: f64,
}

impl Psi {
    fn new() -> Self {
        Self { lin_air: psi_raw(PR_LINEAR, GAMMA_AIR), lin_exh: psi_raw(PR_LINEAR, GAMMA_EXH) }
    }

    #[inline]
    fn psi(&self, pr: f64, gamma: f64) -> f64 {
        if pr >= 1.0 {
            return 0.0;
        }
        if pr > PR_LINEAR {
            let lin = if gamma == GAMMA_AIR {
                self.lin_air
            } else if gamma == GAMMA_EXH {
                self.lin_exh
            } else {
                psi_raw(PR_LINEAR, gamma)
            };
            return lin * (1.0 - pr) / (1.0 - PR_LINEAR);
        }
        psi_raw(py_max(pr, 0.0), gamma)
    }

    #[inline]
    #[allow(clippy::too_many_arguments)]
    fn orifice_g(&self, cd: f64, p_up: f64, t_up: f64, p_dn: f64, t_dn: f64, g: f64, r: f64) -> f64 {
        if cd <= 0.0 {
            return 0.0;
        }
        if p_up >= p_dn {
            if p_up <= 0.0 {
                return 0.0;
            }
            return cd * 1000.0 * p_up / (r * t_up).sqrt() * self.psi(p_dn / p_up, g);
        }
        -(cd * 1000.0 * p_dn / (r * t_dn).sqrt() * self.psi(p_up / p_dn, g))
    }

    #[inline]
    fn orifice(&self, cd: f64, p_up: f64, t_up: f64, p_dn: f64, t_dn: f64) -> f64 {
        self.orifice_g(cd, p_up, t_up, p_dn, t_dn, GAMMA_AIR, R_AIR)
    }
}

fn throttle_area_m2(tps_pct: f64, diameter_m: f64) -> f64 {
    let a_max = PI / 4.0 * diameter_m * diameter_m;
    let a_idle = IDLE_AREA_FRACTION * a_max;
    let tps = py_min(py_max(tps_pct, 0.0), 100.0);
    a_idle + (a_max - a_idle) * (1.0 - (PI / 2.0 * tps / 100.0).cos())
}

// ------------------------------------------------------------------ VE física
#[derive(Clone, Debug)]
pub struct Overlap {
    pub base_deg: f64,
    pub ref_rpm: Vec<f64>,
    pub ref_overlap: Vec<f64>,
}

impl Overlap {
    fn reference_deg(&self, rpm: f64) -> f64 {
        let xs = &self.ref_rpm;
        let ys = &self.ref_overlap;
        let i = bisect_right(xs, rpm);
        if i == 0 {
            return ys[0];
        }
        if i >= xs.len() {
            return ys[ys.len() - 1];
        }
        let (x0, x1) = (xs[i - 1], xs[i]);
        ys[i - 1] + (ys[i] - ys[i - 1]) * (rpm - x0) / (x1 - x0)
    }

    fn delta(&self, rpm: f64, vvt_in: f64, vvt_ex: f64) -> f64 {
        let ov = self.base_deg + vvt_in - vvt_ex;
        let r = self.reference_deg(rpm);
        if ov == r {
            return 0.0;
        }
        (ov / OVERLAP_SCALE_DEG).tanh() - (r / OVERLAP_SCALE_DEG).tanh()
    }

    fn sign(rpm: f64, p_man: f64, p_exh: f64) -> f64 {
        let blend = 0.5 * (1.0 + ((rpm - OVERLAP_RPM_CROSS) / OVERLAP_RPM_WIDTH).tanh());
        let scavenge = ((p_man - p_exh) / SCAVENGE_DP_KPA).tanh();
        -(1.0 - blend) + blend * scavenge
    }
}

#[derive(Clone, Debug)]
pub struct VeModel {
    pub map: Interp2,
    pub rc: f64,
    pub k_vvt: f64,
    pub g_vvt: Option<Interp2>,
    pub overlap: Option<Overlap>,
}

impl VeModel {
    pub fn eval(&self, rpm: f64, map_kpa: f64, p_exh: f64, vvt: f64, vvt_ex: f64) -> f64 {
        let mut ve = self.map.eval(rpm, map_kpa);
        if let Some(g) = &self.g_vvt {
            ve *= 1.0 + self.k_vvt * g.eval(rpm, vvt);
        }
        if let Some(ov) = &self.overlap {
            let d = ov.delta(rpm, vvt, vvt_ex);
            let f = if d == 0.0 {
                1.0
            } else {
                1.0 + K_OVERLAP_VE * d * Overlap::sign(rpm, map_kpa, p_exh)
            };
            ve *= f;
        }
        let ratio = py_max(p_exh, 1.0) / py_max(map_kpa, 1.0);
        let rc = self.rc;
        ve *= (rc - ratio.powf(1.0 / GAMMA_AIR)) / (rc - 1.0);
        py_min(py_max(ve, VE_MIN), VE_MAX)
    }
}

// ------------------------------------------------------------------ turbo
#[derive(Clone, Debug)]
pub struct Compressor {
    pub m_choke_max: f64,
    pub n_max: f64,
    pub n_design: f64,
    pub pr_design: f64,
    pub eta_max: f64,
    pub k1: f64,
    pub k2: f64,
    pub m_peak: f64,
    pub m_range: f64,
    pub n_peak: f64,
    pub table: Option<Interp2>,
}

struct CompPoint {
    m_dot: f64,
    eta: f64,
    margin: f64,
    t_out: f64,
}

impl Compressor {
    fn corrected_flow(&self, pr: f64, n_corr: f64) -> (f64, f64) {
        let n_line = py_min(py_max(n_corr, 0.0), OVERSPEED_LINE_CAP * self.n_max);
        let m_choke = self.m_choke_max * (n_line / self.n_max).powf(0.8);
        let pr0 = 1.0 + (self.pr_design - 1.0) * pw2(n_line / self.n_design);
        if let Some(t) = &self.table {
            return (py_max(t.eval(pr, n_corr), 0.0), m_choke);
        }
        if pr <= 1.0 {
            return (m_choke, m_choke);
        }
        if pr0 <= 1.0 {
            return (0.0, m_choke);
        }
        let y = (pr - 1.0) / (pr0 - 1.0);
        if y >= 1.0 {
            return (0.0, m_choke);
        }
        if y > SPEED_LINE_LINEAR {
            let edge = (1.0 - pw2(SPEED_LINE_LINEAR)).sqrt();
            return (m_choke * edge * (1.0 - y) / (1.0 - SPEED_LINE_LINEAR), m_choke);
        }
        (m_choke * (1.0 - y * y).sqrt(), m_choke)
    }

    fn efficiency(&self, m_corr: f64, n_corr: f64) -> f64 {
        let mut eta = self.eta_max
            * (1.0
                - self.k1 * pw2((m_corr - self.m_peak) / self.m_range)
                - self.k2 * pw2((n_corr - self.n_peak) / self.n_max));
        eta = py_min(py_max(eta, ETA_C_MIN), self.eta_max);
        let over = n_corr / self.n_max - 1.0;
        if over > 0.0 {
            eta *= py_max(OVERSPEED_ETA_FLOOR, 1.0 - OVERSPEED_ETA_SLOPE * over);
        }
        eta
    }

    fn operate(&self, pr: f64, n_rpm: f64, p01: f64, t01: f64) -> CompPoint {
        let theta = t01 / T_REF_K;
        let delta = p01 / P_REF_KPA;
        let n_corr = n_rpm / theta.sqrt();
        let (m_corr, m_choke) = self.corrected_flow(pr, n_corr);
        let m_dot = m_corr * delta / theta.sqrt();
        let eta = self.efficiency(m_corr, n_corr);
        let pr_eff = py_max(pr, 1.0);
        let dt_ideal = t01 * (pr_eff.powf((1.4 - 1.0) / 1.4) - 1.0);
        let t_out = t01 + dt_ideal / eta;
        // Linha de surge recua com √min(N/N_design, 1) abaixo de N_design (T033, B4).
        let speed = py_min(py_max(n_corr, 0.0) / self.n_design, 1.0);
        let surge_line = SURGE_FLOW_FRACTION * m_choke * speed.sqrt();
        let margin =
            if surge_line > 0.0 && pr > SURGE_PR_MIN { m_corr / surge_line - 1.0 } else { 1.0 };
        CompPoint { m_dot, eta, margin, t_out }
    }
}

#[derive(Clone, Debug)]
pub struct Turbo {
    pub compressor: Compressor,
    pub area_m2: f64,
    pub wg_area_max_m2: f64,
    pub eta: Interp1,
    pub blow_off_valve: bool,
    pub inertia: f64,
    pub friction_k: f64,
    pub comp_passive_area: f64,
}

impl Turbo {
    fn power_w(&self, m_t: f64, p03: f64, t03: f64, p04: f64) -> f64 {
        if m_t <= 0.0 || p03 <= p04 {
            return 0.0;
        }
        let pr_t = p03 / p04;
        let eta = self.eta.eval(pr_t);
        let expo = (GAMMA_EXH - 1.0) / GAMMA_EXH;
        m_t * CP_EXH * t03 * eta * (1.0 - (1.0 / pr_t).powf(expo))
    }
}

#[inline]
fn shaft_acceleration(omega: f64, p_turb: f64, p_comp: f64, inertia: f64, friction_k: f64) -> f64 {
    let drive = (p_turb - p_comp) / (inertia * py_max(omega, OMEGA_FLOOR));
    drive - friction_k * omega / inertia
}

// ------------------------------------------------------------------ supercharger
#[derive(Clone, Debug)]
pub struct Supercharger {
    pub disp_m3: f64,
    pub pulley_ratio: f64,
    pub k_leak: f64,
    pub n_ref_rpm: f64,
    pub mech_efficiency: f64,
    pub eta_ad: Interp1,
    pub bypass_valve: bool,
}

struct ScPoint {
    rotor_rpm: f64,
    m_dot: f64,
    eta_ad: f64,
    t_out: f64,
    power_kw: f64,
}

impl Supercharger {
    fn operate(&self, engine_rpm: f64, p_in: f64, t_in: f64, p_out: f64) -> ScPoint {
        let n_sc = py_max(engine_rpm, 0.0) * self.pulley_ratio;
        let pr = py_max(p_out, 1.0) / py_max(p_in, 1.0);
        let eta_v = if n_sc <= 0.0 {
            ETA_V_MIN
        } else {
            let e = 1.0 - self.k_leak * (pr - 1.0) * self.n_ref_rpm / n_sc;
            py_min(py_max(e, ETA_V_MIN), ETA_V_MAX)
        };
        let rho_in = 1000.0 * py_max(p_in, 0.0) / (R_AIR * t_in);
        let m_dot = rho_in * self.disp_m3 * n_sc / 60.0 * eta_v;
        let eta_ad = self.eta_ad.eval(py_max(pr, 1.0));
        let pr_eff = py_max(pr, 1.0);
        let t_out = t_in * (1.0 + (pr_eff.powf(0.4 / 1.4) - 1.0) / eta_ad);
        let power_kw = m_dot * CP_AIR * (t_out - t_in) / self.mech_efficiency / 1000.0;
        ScPoint { rotor_rpm: n_sc, m_dot, eta_ad, t_out, power_kw }
    }
}

// ------------------------------------------------------------------ motor
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Induction {
    Natural,
    Turbo,
    Supercharger,
}

#[derive(Clone, Debug)]
pub struct Intercooler {
    pub present: bool,
    pub effectiveness: f64,
    pub k_dp: f64,
}

#[derive(Clone, Debug)]
pub struct GasConfig {
    pub induction: Induction,
    pub pre_compressor: bool,
    pub has_boost_volume: bool,
    pub v_boost: f64,
    pub v_man: f64,
    pub v_exh: f64,
    pub throttle_d: f64,
    pub vd_total_m3: f64,
    pub exh_backpressure_kpa: f64,
    pub exh_ref_flow: f64,
    pub na_exhaust_area: f64,
    pub n_substeps: usize,
    pub h: f64,
    pub ve: VeModel,
    pub turbo: Option<Turbo>,
    pub sc: Option<Supercharger>,
    pub ic: Intercooler,
}

/// Estado do `EngineVars` lido/escrito pelo bloco de gás (ordem = `GAS_STATE_FIELDS`).
#[derive(Clone, Copy, Debug, Default)]
pub struct GasState {
    pub p_amb: f64,
    pub t_amb: f64,
    pub fan: f64,
    pub rpm: f64,
    pub throttle_pct: f64,
    pub vvt_in: f64,
    pub vvt_ex: f64,
    pub wastegate_x: f64,
    pub fuel_rate: f64,
    pub egt_col: f64,
    pub p_boost: f64,
    pub p_man: f64,
    pub p_exh: f64,
    pub t_boost: f64,
    pub t_man: f64,
    pub turbo_omega: f64,
    pub ic_core: f64,
    pub m_comp: f64,
    pub m_exh_out: f64,
    pub surge_s: f64,
    pub m_throttle_cum: f64,
}

/// Diagnóstico do tick (campos de `_Flows`).
#[derive(Clone, Copy, Debug)]
pub struct Diag {
    pub m_thr: f64,
    pub m_comp: f64,
    pub m_eng: f64,
    pub m_turb: f64,
    pub m_wg: f64,
    pub m_out: f64,
    pub p_turb_w: f64,
    pub p_comp_w: f64,
    pub t_comp_out_k: f64,
    pub pr_comp: f64,
    pub eta_comp: f64,
    pub surge_margin: f64,
    pub sc_power_kw: f64,
    pub sc_rpm: f64,
    pub ve: f64,
}

impl Default for Diag {
    fn default() -> Self {
        Self {
            m_thr: 0.0,
            m_comp: 0.0,
            m_eng: 0.0,
            m_turb: 0.0,
            m_wg: 0.0,
            m_out: 0.0,
            p_turb_w: 0.0,
            p_comp_w: 0.0,
            t_comp_out_k: 0.0,
            pr_comp: 1.0,
            eta_comp: 0.0,
            surge_margin: 1.0,
            sc_power_kw: 0.0,
            sc_rpm: 0.0,
            ve: 0.0,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct GasCommand {
    pub bypass_open: bool,
    pub antilag_air_pct: f64,
    pub leak: f64,
}

const MAX_N: usize = 3;

pub struct GasModel {
    pub cfg: GasConfig,
    psi: Psi,
}

impl GasModel {
    pub fn new(cfg: GasConfig) -> Self {
        Self { cfg, psi: Psi::new() }
    }

    pub fn ve(&self, rpm: f64, map_kpa: f64, p_exh: f64, vvt: f64, vvt_ex: f64) -> f64 {
        self.cfg.ve.eval(rpm, map_kpa, p_exh, vvt, vvt_ex)
    }

    #[inline]
    fn n(&self) -> usize {
        if self.cfg.has_boost_volume {
            3
        } else {
            2
        }
    }

    /// `_flows`: taxas dp/dt do vetor `x`; preenche `diag` quando pedido.
    #[allow(clippy::too_many_lines, unused_assignments)]
    fn flows(
        &self,
        v: &GasState,
        x: &[f64; MAX_N],
        cmd: &GasCommand,
        omega: f64,
        diag: Option<&mut Diag>,
    ) -> [f64; MAX_N] {
        let c = &self.cfg;
        let ps = &self.psi;
        let p_amb = v.p_amb;
        let t_amb = v.t_amb;
        let (mut p_b, mut p_m, mut p_e) =
            if c.has_boost_volume { (x[0], x[1], x[2]) } else { (p_amb, x[0], x[1]) };
        p_m = py_max(p_m, 0.5);
        p_e = py_max(p_e, 0.5);
        p_b = py_max(p_b, 0.5);
        let rpm = v.rpm;
        let t_m = v.t_man;
        let t_b = v.t_boost;
        let t_e = v.egt_col;
        let area_thr = CD_THROTTLE * throttle_area_m2(v.throttle_pct, c.throttle_d);
        let ve = if rpm > 0.0 { c.ve.eval(rpm, p_m, p_e, v.vvt_in, v.vvt_ex) } else { 0.0 };
        let m_eng = ve * 1000.0 * p_m / (R_AIR * t_m) * c.vd_total_m3 * rpm / 120.0;
        let m_fuel = v.fuel_rate;
        let (mut m_comp, mut m_thr, mut m_bypass, mut m_al, mut m_leak) = (0.0, 0.0, 0.0, 0.0, 0.0);
        let (mut p_turb, mut p_comp) = (0.0, 0.0);
        let (mut sc_kw, mut sc_rpm) = (0.0, 0.0);
        let mut pr = 1.0;
        let mut eta = 0.0;
        let mut surge = 1.0;
        let mut t_comp_out = t_amb;
        let p04 = p_amb + c.exh_backpressure_kpa * pw2(v.m_exh_out / c.exh_ref_flow);
        let m_t;
        let m_wg;
        let mut rates = [0.0; MAX_N];
        match c.induction {
            Induction::Turbo => {
                let tb = c.turbo.as_ref().expect("turbo");
                let dp_ic = c.ic.k_dp * v.m_comp * v.m_comp;
                pr = (p_b + dp_ic) / p_amb;
                let point = tb.compressor.operate(pr, omega * 30.0 / PI, p_amb, t_amb);
                m_comp = point.m_dot;
                if v.surge_s >= 0.0 {
                    m_comp *= 1.0
                        + 0.05 * (2.0 * PI * 8.0 * v.surge_s).sin() * (-v.surge_s / 0.5).exp();
                }
                if p_b < p_amb {
                    let lim =
                        py_max(ps.orifice(tb.comp_passive_area, p_amb, t_amb, p_b, t_amb), 0.0);
                    m_comp = py_max(m_comp, lim);
                }
                p_comp = m_comp * 1005.0 * (point.t_out - t_amb);
                eta = point.eta;
                surge = point.margin;
                t_comp_out = point.t_out;
                m_thr = ps.orifice(area_thr, p_b, t_b, p_m, t_m);
                if cmd.bypass_open && tb.blow_off_valve {
                    m_bypass = ps.orifice(BOV_AREA_M2, p_b, t_b, p_amb, t_amb);
                }
                m_leak = ps.orifice(cmd.leak, p_b, t_b, p_amb, t_amb);
                if cmd.antilag_air_pct > 0.0 {
                    m_al = py_max(
                        ps.orifice(
                            ANTILAG_AREA_M2 * cmd.antilag_air_pct / 100.0,
                            p_b,
                            t_b,
                            p_e,
                            t_e,
                        ),
                        0.0,
                    );
                }
                m_t = py_max(ps.orifice_g(tb.area_m2, p_e, t_e, p04, t_e, GAMMA_EXH, R_EXH), 0.0);
                let wg_area = tb.wg_area_max_m2 * py_min(py_max(v.wastegate_x, 0.0), 1.0);
                m_wg = py_max(ps.orifice_g(wg_area, p_e, t_e, p04, t_e, GAMMA_EXH, R_EXH), 0.0);
                p_turb = tb.power_w(m_t, p_e, t_e, p04);
                let c_b = R_AIR * t_b / c.v_boost / 1000.0;
                let c_m = R_AIR * t_m / c.v_man / 1000.0;
                let c_e = 287.0 * t_e / c.v_exh / 1000.0;
                rates[0] = c_b * (m_comp - m_thr - m_bypass - m_leak - m_al);
                rates[1] = c_m * (m_thr - m_eng);
                rates[2] = c_e * (m_eng + m_fuel + m_al - m_t - m_wg);
            }
            _ => {
                m_t = 0.0;
                m_wg = ps.orifice_g(c.na_exhaust_area, p_e, t_e, p04, t_e, 1.33, 287.0);
                let c_m = R_AIR * t_m / c.v_man / 1000.0;
                let c_e = 287.0 * t_e / c.v_exh / 1000.0;
                if c.induction == Induction::Natural {
                    m_thr = ps.orifice(area_thr, p_amb, t_amb, p_m, t_m);
                    m_leak = -ps.orifice(cmd.leak, p_m, t_m, p_amb, t_amb);
                    rates[0] = c_m * (m_thr + m_leak - m_eng);
                    rates[1] = c_e * (m_eng + m_fuel - m_wg);
                } else {
                    let sc = c.sc.as_ref().expect("supercharger");
                    let c_b = R_AIR * t_b / c.v_boost / 1000.0;
                    let point;
                    if c.pre_compressor {
                        m_thr = ps.orifice(area_thr, p_amb, t_amb, p_b, t_amb);
                        point = sc.operate(rpm, p_b, t_amb, p_m);
                        if cmd.bypass_open && sc.bypass_valve {
                            m_bypass = ps.orifice(BYPASS_AREA_M2, p_m, t_m, p_b, t_amb);
                        }
                        m_leak = ps.orifice(cmd.leak, p_m, t_m, p_amb, t_amb);
                        rates[0] = c_b * (m_thr - point.m_dot + m_bypass);
                        rates[1] = c_m * (point.m_dot - m_bypass - m_eng - m_leak);
                        rates[2] = c_e * (m_eng + m_fuel - m_wg);
                    } else {
                        point = sc.operate(rpm, p_amb, t_amb, p_b);
                        if cmd.bypass_open && sc.bypass_valve {
                            m_bypass = ps.orifice(BYPASS_AREA_M2, p_b, t_b, p_amb, t_amb);
                        }
                        m_thr = ps.orifice(area_thr, p_b, t_b, p_m, t_m);
                        m_leak = ps.orifice(cmd.leak, p_b, t_b, p_amb, t_amb);
                        rates[0] = c_b * (point.m_dot - m_bypass - m_thr - m_leak);
                        rates[1] = c_m * (m_thr - m_eng);
                        rates[2] = c_e * (m_eng + m_fuel - m_wg);
                    }
                    m_comp = point.m_dot;
                    sc_kw = point.power_kw;
                    sc_rpm = point.rotor_rpm;
                    t_comp_out = point.t_out;
                    pr = if c.pre_compressor { p_m / p_b } else { p_b / p_amb };
                    eta = point.eta_ad;
                }
            }
        }
        if let Some(d) = diag {
            d.m_thr = m_thr;
            d.m_comp = m_comp;
            d.m_eng = m_eng;
            d.m_turb = m_t;
            d.m_wg = m_wg;
            d.m_out = m_t + m_wg;
            d.p_turb_w = p_turb;
            d.p_comp_w = p_comp;
            d.t_comp_out_k = t_comp_out;
            d.pr_comp = pr;
            d.eta_comp = eta;
            d.surge_margin = surge;
            d.sc_power_kw = sc_kw;
            d.sc_rpm = sc_rpm;
            d.ve = ve;
        }
        rates
    }

    /// `linear_implicit_step` + `_solve` (Gauss com pivotagem parcial).
    fn implicit_step(
        &self,
        v: &GasState,
        x: &[f64; MAX_N],
        cmd: &GasCommand,
        omega: f64,
        h: f64,
        f: &[f64; MAX_N],
    ) -> Result<[f64; MAX_N], String> {
        let n = self.n();
        let mut jac = [[0.0_f64; MAX_N]; MAX_N]; // jac[col][row]
        for j in 0..n {
            let mut xp = *x;
            xp[j] += FD_STEP_KPA;
            let fp = self.flows(v, &xp, cmd, omega, None);
            for i in 0..n {
                jac[j][i] = (fp[i] - f[i]) / FD_STEP_KPA;
            }
        }
        let mut m = [[0.0_f64; MAX_N + 1]; MAX_N];
        for i in 0..n {
            for j in 0..n {
                m[i][j] = (if i == j { 1.0 } else { 0.0 }) - h * jac[j][i];
            }
            m[i][n] = h * f[i];
        }
        for col in 0..n {
            let mut piv = col;
            for r in col + 1..n {
                if m[r][col].abs() > m[piv][col].abs() {
                    piv = r;
                }
            }
            if m[piv][col] == 0.0 {
                return Err("matriz singular no integrador de pressões".into());
            }
            if piv != col {
                m.swap(col, piv);
            }
            let inv = 1.0 / m[col][col];
            for r in col + 1..n {
                let factor = m[r][col] * inv;
                if factor != 0.0 {
                    for cc in col..=n {
                        m[r][cc] -= factor * m[col][cc];
                    }
                }
            }
        }
        let mut dx = [0.0_f64; MAX_N];
        for r in (0..n).rev() {
            let mut acc = m[r][n];
            for cc in r + 1..n {
                acc -= m[r][cc] * dx[cc];
            }
            dx[r] = acc / m[r][r];
        }
        let mut out = [0.0_f64; MAX_N];
        for i in 0..n {
            out[i] = x[i] + dx[i];
        }
        Ok(out)
    }

    /// `_gas`: todos os subpassos de um tick; devolve o diagnóstico do último.
    pub fn step(&self, v: &mut GasState, cmd: &GasCommand) -> Result<Diag, String> {
        let c = &self.cfg;
        let h = c.h;
        let n = self.n();
        let mut diag = Diag::default();
        for _ in 0..c.n_substeps {
            let omega = v.turbo_omega;
            let mut x = [0.0_f64; MAX_N];
            if c.has_boost_volume {
                x[0] = v.p_boost;
                x[1] = v.p_man;
                x[2] = v.p_exh;
            } else {
                x[0] = v.p_man;
                x[1] = v.p_exh;
            }
            let f0 = self.flows(v, &x, cmd, omega, Some(&mut diag));
            let mut a1 = 0.0;
            let omega_pred = if let Some(tb) = &c.turbo {
                a1 = shaft_acceleration(omega, diag.p_turb_w, diag.p_comp_w, tb.inertia, tb.friction_k);
                py_max(omega + h * a1, 0.0)
            } else {
                0.0
            };
            let mut x_new = self.implicit_step(v, &x, cmd, omega, h, &f0)?;
            for xi in x_new.iter_mut().take(n) {
                *xi = py_max(*xi, 1.0);
            }
            if c.has_boost_volume {
                v.p_boost = x_new[0];
                v.p_man = x_new[1];
                v.p_exh = x_new[2];
            } else {
                v.p_man = x_new[0];
                v.p_exh = x_new[1];
                v.p_boost = v.p_amb;
            }
            self.flows(v, &x_new, cmd, omega_pred, Some(&mut diag));
            if let Some(tb) = &c.turbo {
                let a2 = shaft_acceleration(
                    omega_pred,
                    diag.p_turb_w,
                    diag.p_comp_w,
                    tb.inertia,
                    tb.friction_k,
                );
                v.turbo_omega = py_max(omega + 0.5 * h * (a1 + a2), 0.0);
                v.surge_s = if diag.surge_margin < 0.0 {
                    if v.surge_s >= 0.0 {
                        v.surge_s + h
                    } else {
                        0.0
                    }
                } else {
                    -1.0
                };
            }
            if c.induction != Induction::Natural {
                v.ic_core += h * self.ic_core_rate(v.ic_core, diag.t_comp_out_k, diag.m_comp, v.t_amb, v.fan);
                let t_out = if c.ic.present {
                    diag.t_comp_out_k - c.ic.effectiveness * (diag.t_comp_out_k - v.ic_core)
                } else {
                    diag.t_comp_out_k
                };
                if c.pre_compressor {
                    v.t_boost = v.t_amb;
                    v.t_man = t_out;
                } else {
                    v.t_boost = t_out;
                    v.t_man = t_out;
                }
            } else {
                v.t_boost = v.t_amb;
                v.t_man = v.t_amb;
            }
            v.m_comp = diag.m_comp;
            v.m_exh_out = diag.m_out;
            v.m_throttle_cum += h * diag.m_thr;
        }
        Ok(diag)
    }

    fn ic_core_rate(&self, t_core: f64, t_in: f64, m_dot: f64, t_amb: f64, fan: f64) -> f64 {
        let ic = &self.cfg.ic;
        if !ic.present {
            return 0.0;
        }
        let q_in = py_max(m_dot, 0.0) * CP_AIR * ic.effectiveness * (t_in - t_core);
        let ha = IC_HA_BASE_W_K + IC_HA_FAN_W_K_PER_M_S * fan;
        (q_in - ha * (t_core - t_amb)) / IC_CAPACITY_J_K
    }
}
