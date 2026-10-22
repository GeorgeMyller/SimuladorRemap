//! Fecho térmico do tick: ECT, óleo, EGT por cilindro/coletor, termopares, pistão e ponto
//! quente (espelho do trecho "Temperaturas lumpadas" + "EGT" de `PhysicsEngine._finish`).

use super::interp::{py_max, py_min};

const K0: f64 = 273.15;
const LOAD_REF_KPA: f64 = 2000.0;
const CYLINDER_GAS_TAU_S: f64 = 0.05;
const COLLECTOR_TAU_S: f64 = 0.3;
const EGT_PROBE_UA_FRACTION: f64 = 0.25;
const EXH_MANIFOLD_WALL_ABOVE_ECT_K: f64 = 250.0;
const CP_EXH_J_KG_K: f64 = 1200.0;
const MIN_FLOW_KG_S: f64 = 1e-6;
const PISTON_TAU_S: f64 = 8.0;
const HOT_SPOT_TAU_S: f64 = 2.0;
const PISTON_HEAT_SHARE: f64 = 0.30;
const PISTON_HA_W_K: f64 = 45.0;
const HOT_SPOT_EGT_SHARE: f64 = 0.75;
const OIL_TAU_S: f64 = 90.0;
const OIL_LOAD_RISE_K: f64 = 15.0;
const COOL_CAPACITY_J_K: f64 = 60_000.0;
const COOL_SHARE: f64 = 0.5;
const COOL_UA_BASE_W_K: f64 = 30.0;
const COOL_UA_RADIATOR_W_K: f64 = 300.0;
const COOL_UA_FAN_W_K_PER_M_S: f64 = 80.0;
const THERMOSTAT_OPEN_C: f64 = 88.0;
const THERMOSTAT_FULL_C: f64 = 98.0;

/// `math.fsum` do CPython (Shewchuk com correção de meio-ulp), bit a bit.
pub fn fsum(values: impl IntoIterator<Item = f64>) -> f64 {
    let mut p: Vec<f64> = Vec::with_capacity(8);
    let mut special = 0.0_f64;
    let mut has_special = false;
    for xv in values {
        let mut x = xv;
        let mut i = 0usize;
        for j in 0..p.len() {
            let mut y = p[j];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let yr = hi - x;
            let lo = y - yr;
            if lo != 0.0 {
                p[i] = lo;
                i += 1;
            }
            x = hi;
        }
        p.truncate(i);
        if x != 0.0 {
            if !x.is_finite() {
                special += xv;
                has_special = true;
                p.clear();
            } else {
                p.push(x);
            }
        }
    }
    if has_special {
        return special;
    }
    let mut n = p.len();
    let mut hi = 0.0_f64;
    if n > 0 {
        n -= 1;
        hi = p[n];
        let mut lo = 0.0_f64;
        while n > 0 {
            let x = hi;
            n -= 1;
            let y = p[n];
            hi = x + y;
            let yr = hi - x;
            lo = y - yr;
            if lo != 0.0 {
                break;
            }
        }
        if n > 0 && ((lo < 0.0 && p[n - 1] < 0.0) || (lo > 0.0 && p[n - 1] > 0.0)) {
            let y = lo * 2.0;
            let x = hi + y;
            let yr = x - hi;
            if y == yr {
                hi = x;
            }
        }
    }
    hi
}

#[inline]
fn first_order(y: f64, x: f64, dt: f64, tau: f64) -> f64 {
    y + (1.0 - (-dt / tau).exp()) * (x - y)
}

#[inline]
fn manifold_heat_loss(t_mix: f64, m_dot: f64, ua: f64, ect_c: f64) -> f64 {
    let t_wall = ect_c + 273.15 + EXH_MANIFOLD_WALL_ABOVE_ECT_K;
    if m_dot <= MIN_FLOW_KG_S {
        return t_mix;
    }
    t_wall + (t_mix - t_wall) * (-ua / (m_dot * CP_EXH_J_KG_K)).exp()
}

fn coolant_rate(ect_c: f64, wall_heat_w: f64, t_amb_c: f64, fan: f64) -> f64 {
    let span = THERMOSTAT_FULL_C - THERMOSTAT_OPEN_C;
    let opening = py_min(py_max((ect_c - THERMOSTAT_OPEN_C) / span, 0.0), 1.0);
    let ua = COOL_UA_BASE_W_K + opening * (COOL_UA_RADIATOR_W_K + COOL_UA_FAN_W_K_PER_M_S * fan);
    let q_in = COOL_SHARE * py_max(wall_heat_w, 0.0);
    (q_in - ua * (ect_c - t_amb_c)) / COOL_CAPACITY_J_K
}

#[derive(Clone, Debug)]
pub struct ThermalConfig {
    pub n_cyl: usize,
    pub exh_ua_w_k: f64,
    pub egt_backpressure_factor: f64,
    pub tau_tc: f64,
}

/// Entradas escalares do fecho térmico.
#[derive(Clone, Copy, Debug)]
pub struct ThermalScalars {
    pub running: bool,
    pub rpm: f64,
    pub dt: f64,
    pub imep: f64,
    pub t_amb_k: f64,
    pub fan: f64,
    pub ect_c: f64,
    pub oil_c: f64,
    pub egt_col_k: f64,
    pub tc_col_c: f64,
}

/// Vetores por cilindro (`egt_gas`, `tc_egt`, `piston`, `hot_spot` são atualizados no lugar).
pub struct ThermalCylinders<'a> {
    pub qwall_last: &'a [f64],
    pub m_air_last: &'a [f64],
    pub m_fuel_last: &'a [f64],
    pub port_k_last: &'a [f64],
    pub fire_last: &'a [f64],
    pub egt_gas: &'a mut [f64],
    pub tc_egt: &'a mut [f64],
    pub piston: &'a mut [f64],
    pub hot_spot: &'a mut [f64],
    pub egt_probe: &'a mut [f64],
}

/// Devolve `(ect, oil, egt_col, tc_col)`.
pub fn step(cfg: &ThermalConfig, s: &ThermalScalars, c: ThermalCylinders<'_>) -> (f64, f64, f64, f64) {
    let n = cfg.n_cyl;
    let dt = s.dt;
    let running = s.running;
    let rpm = s.rpm;
    let cyc_hz = if running { rpm / 120.0 } else { 0.0 };
    let q_wall: Vec<f64> = c.qwall_last.iter().map(|&q| py_max(q, 0.0) * cyc_hz).collect();
    let mut ect = s.ect_c;
    ect += dt * coolant_rate(ect, fsum(q_wall.iter().copied()), s.t_amb_k - K0, s.fan);
    let load_frac = if running { s.imep / LOAD_REF_KPA } else { 0.0 };
    let target = ect + OIL_LOAD_RISE_K * py_min(py_max(load_frac, 0.0), 1.0);
    let oil = s.oil_c + dt * ((target - s.oil_c) / OIL_TAU_S);
    let tau_tc = cfg.tau_tc;
    let cool_target = ect + K0;
    let m_ex: Vec<f64> = (0..n).map(|i| c.m_air_last[i] + c.m_fuel_last[i]).collect();
    let ua_probe = cfg.exh_ua_w_k * EGT_PROBE_UA_FRACTION / n as f64;
    let cyc_flow = if running { rpm / 120.0 } else { 0.0 };
    let gain_piston = 1.0 - (-dt / PISTON_TAU_S).exp();
    let gain_hot = 1.0 - (-dt / HOT_SPOT_TAU_S).exp();
    for i in 0..n {
        if running {
            c.egt_gas[i] = first_order(c.egt_gas[i], c.port_k_last[i], dt, CYLINDER_GAS_TAU_S);
            c.egt_probe[i] = manifold_heat_loss(c.egt_gas[i], m_ex[i] * cyc_flow, ua_probe, ect);
        } else {
            c.egt_gas[i] = first_order(c.egt_gas[i], cool_target, dt, 5.0);
            c.egt_probe[i] = c.egt_gas[i];
        }
        c.tc_egt[i] = first_order(c.tc_egt[i], c.egt_probe[i] - K0, dt, tau_tc);
        let firing = running && c.fire_last[i] > 0.0;
        let p_target = ect + PISTON_HEAT_SHARE * py_max(q_wall[i], 0.0) / PISTON_HA_W_K;
        c.piston[i] += gain_piston * (p_target - c.piston[i]);
        let egt_c = c.egt_probe[i] - K0;
        let h_target =
            if firing { ect + HOT_SPOT_EGT_SHARE * py_max(egt_c - ect, 0.0) } else { ect };
        c.hot_spot[i] += gain_hot * (h_target - c.hot_spot[i]);
    }
    let m_tot = fsum(m_ex.iter().copied());
    let mut col_target = if m_tot > 0.0 {
        fsum((0..n).map(|i| m_ex[i] * c.egt_gas[i])) / m_tot
    } else {
        fsum(c.egt_gas.iter().copied()) / n as f64
    };
    if running {
        col_target = manifold_heat_loss(col_target, m_tot * rpm / 120.0, cfg.exh_ua_w_k, ect);
        if cfg.egt_backpressure_factor != 1.0 {
            let t_wall = ect + K0 + EXH_MANIFOLD_WALL_ABOVE_ECT_K;
            col_target = t_wall + (col_target - t_wall) * cfg.egt_backpressure_factor;
        }
    }
    let egt_col = first_order(s.egt_col_k, col_target, dt, COLLECTOR_TAU_S);
    let tc_col = first_order(s.tc_col_c, egt_col - K0, dt, tau_tc);
    (ect, oil, egt_col, tc_col)
}
