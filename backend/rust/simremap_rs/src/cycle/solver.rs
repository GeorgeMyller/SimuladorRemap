//! Ciclo fechado de zona única IVC → EVO (espelho de `CycleSolver.solve_uncached`).
//!
//! Heun a 1° de cambota com γ(T), Woschni, Wiebe e duração de Metghalchi-Keck. A ordem das
//! operações é a do Python (sem FMA, mesmas chamadas de `pow`/`exp`/`ln` da libm), o que dá
//! paridade bit a bit na mesma plataforma.

use super::interp::{pw2, py_max, py_min};

pub const R_MIX: f64 = 287.0;
const GAMMA_A: f64 = 1.392;
const GAMMA_B: f64 = 8.13e-5;
const GAMMA_MIN: f64 = 1.20;
const GAMMA_MAX: f64 = 1.40;
const T_GAMMA_SAT: f64 = (GAMMA_A - GAMMA_MIN) / GAMMA_B;
const WOSCHNI_C1: f64 = 2.28;
const WOSCHNI_C2: f64 = 3.24e-3;
const POLYTROPIC_MOTORED: f64 = 1.30;
const DEG_OFFSET: i64 = 360;
const COMBUSTION_EFFICIENCY: f64 = 0.98;
const IGNITION_DELAY_REF_DEG: f64 = 4.0;
const RESIDUAL_DURATION_GAIN: f64 = 2.2;
const RESIDUAL_SPEED_LOSS: f64 = 2.1;
const RPM_EXPONENT: f64 = 0.37;
const GASOLINE: Flame = Flame { b_m: 0.305, b_phi: -0.549, phi_m: 1.21 };

#[derive(Clone, Copy, Debug)]
pub struct Flame {
    pub b_m: f64,
    pub b_phi: f64,
    pub phi_m: f64,
}

#[inline]
pub fn gamma_of_t(t_k: f64) -> f64 {
    let g = GAMMA_A - GAMMA_B * t_k;
    if g < GAMMA_MIN {
        return GAMMA_MIN;
    }
    if g > GAMMA_MAX {
        return GAMMA_MAX;
    }
    g
}

pub fn internal_energy_per_kg(t_k: f64) -> f64 {
    let t_low = (GAMMA_A - GAMMA_MAX) / GAMMA_B;
    if t_k <= T_GAMMA_SAT {
        let t = py_max(t_k, t_low + 1e-9);
        return -(R_MIX / GAMMA_B) * (GAMMA_A - 1.0 - GAMMA_B * t).ln();
    }
    let u_sat = -(R_MIX / GAMMA_B) * (GAMMA_A - 1.0 - GAMMA_B * T_GAMMA_SAT).ln();
    u_sat + R_MIX / (GAMMA_MIN - 1.0) * (t_k - T_GAMMA_SAT)
}

#[inline]
pub fn wiebe_fraction(theta: f64, theta0: f64, duration: f64, a: f64, m: f64) -> f64 {
    if theta <= theta0 {
        return 0.0;
    }
    let y = py_min((theta - theta0) / duration, 1.0);
    1.0 - (-a * y.powf(m + 1.0)).exp()
}

pub fn laminar_flame_speed(c: Flame, lam: f64, t_u_k: f64, p_kpa: f64, x_r: f64) -> f64 {
    let phi = 1.0 / lam;
    let mut s_l0 = c.b_m + c.b_phi * pw2(phi - c.phi_m);
    s_l0 = py_max(s_l0, 0.02);
    let alpha = 2.18 - 0.8 * (phi - 1.0);
    let beta = -0.16 + 0.22 * (phi - 1.0);
    let dilution = py_max(1.0 - RESIDUAL_SPEED_LOSS * x_r, 0.05);
    s_l0 * (t_u_k / 298.0).powf(alpha) * (py_max(p_kpa, 1.0) / 101.325).powf(beta) * dilution
}

#[allow(clippy::too_many_arguments)]
pub fn burn_duration_deg(
    rpm: f64,
    lam: f64,
    c: Flame,
    x_r: f64,
    t_u_k: f64,
    p_kpa: f64,
    duration_ref_deg: f64,
    rpm_ref: f64,
) -> f64 {
    let s_l = laminar_flame_speed(c, lam, t_u_k, p_kpa, x_r);
    let rpm_term = (py_max(rpm, 100.0) / rpm_ref).powf(RPM_EXPONENT);
    let s_ref = laminar_flame_speed(GASOLINE, 1.0, t_u_k, p_kpa, 0.0);
    let residual = 1.0 + RESIDUAL_DURATION_GAIN * x_r;
    let duration = duration_ref_deg * rpm_term * (s_ref / s_l).sqrt() * residual;
    py_min(py_max(duration, 15.0), 140.0)
}

#[inline]
pub fn ignition_delay_deg(rpm: f64) -> f64 {
    IGNITION_DELAY_REF_DEG * (py_max(rpm, 0.0) / 3000.0).sqrt()
}

/// Geometria e constantes do solver (fixas por motor).
#[derive(Clone, Debug)]
pub struct CycleGeometry {
    pub volume: Vec<f64>,
    pub dvol: Vec<f64>,
    pub area: Vec<f64>,
    pub stroke_m: f64,
    pub vd_cyl_m3: f64,
    pub woschni_k: f64,
    pub wiebe_a: f64,
    pub wiebe_m: f64,
    pub duration_ref_deg: f64,
    pub rpm_ref: f64,
}

/// Entradas quantizadas de um ciclo + termoquímica do combustível.
#[derive(Clone, Copy, Debug)]
pub struct CycleInputs {
    pub rpm: f64,
    pub m_air_kg: f64,
    pub lam: f64,
    pub x_r: f64,
    pub t_ivc_k: f64,
    pub advance_deg: f64,
    pub ivc_deg: i64,
    pub evo_deg: i64,
    pub t_wall_k: f64,
    pub fire: bool,
    pub afr: f64,
    pub lhv_j_kg: f64,
    pub flame: Flame,
}

/// Resultado com os mesmos campos de `CycleResult` (menos `inputs`).
#[derive(Clone, Debug, Default)]
pub struct CycleOutput {
    pub pressure_pa: Vec<f64>,
    pub temperature_k: Vec<f64>,
    pub m_total_kg: f64,
    pub m_fuel_kg: f64,
    pub q_available_j: f64,
    pub q_comb_j: f64,
    pub q_wall_j: f64,
    pub work_j: f64,
    pub du_j: f64,
    pub energy_error: f64,
    pub p_max_pa: f64,
    pub theta_pmax_deg: f64,
    pub t_evo_k: f64,
    pub p_evo_pa: f64,
    pub xb_evo: f64,
    pub burn_duration_deg: f64,
    pub theta0_deg: f64,
    pub spark_deg: f64,
    pub unburned_chem_j: f64,
    pub event_theta_start: i64,
    pub event_pressure_kpa: Vec<f64>,
    pub event_t_unburned_k: Vec<f64>,
    pub event_burned_fraction: Vec<f64>,
    pub t_unburned_max_k: f64,
}

struct Ctx<'a> {
    vol: &'a [f64],
    motored: &'a [f64],
    c1sp_08: f64,
    dvol: &'a [f64],
    area: &'a [f64],
    mr: f64,
    c1sp: f64,
    c2k: f64,
    hk: f64,
    p_ivc: f64,
    t_wall: f64,
}

/// `(V_ivc / V(θ))^1,3` para todos os ângulos de um IVC (a compressão politrópica de referência).
pub fn motored_table(volume: &[f64], i0: usize) -> Vec<f64> {
    let v_ivc = volume[i0];
    volume.iter().map(|&v| (v_ivc / v).powf(POLYTROPIC_MOTORED)).collect()
}

impl Ctx<'_> {
    #[inline]
    fn deriv(&self, i: usize, p: f64, dqc: f64, comb: bool) -> (f64, f64) {
        let v = self.vol[i];
        let t = p * v / self.mr;
        let mut g = GAMMA_A - GAMMA_B * t;
        g = if g < GAMMA_MIN { GAMMA_MIN } else { py_min(g, GAMMA_MAX) };
        // `w^0.8` sem combustão é a constante `c1sp^0.8`; `(V_ivc/V)^1,3` vem da tabela do IVC.
        let w08 = if comb {
            let p_mot = self.p_ivc * self.motored[i];
            let mut w = self.c1sp;
            w += self.c2k * (p - p_mot);
            w = py_max(w, self.c1sp);
            w.powf(0.8)
        } else {
            self.c1sp_08
        };
        let h_dt = self.hk * (p / 1000.0).powf(0.8) * t.powf(-0.55) * w08;
        let dqw = h_dt * self.area[i] * (t - self.t_wall);
        (((g - 1.0) * (dqc - dqw) - g * p * self.dvol[i]) / v, dqw)
    }
}

/// Resolve um ciclo. `Err` se os ângulos saem da tabela de 721 pontos.
///
/// `motored(i0)` devolve `motored_table(volume, i0)` (o chamador pode guardá-la em cache).
pub fn solve<'m>(
    geo: &CycleGeometry,
    inp: &CycleInputs,
    motored: impl FnOnce(usize) -> &'m [f64],
) -> Result<CycleOutput, String> {
    let i0 = inp.ivc_deg + DEG_OFFSET;
    let i1 = inp.evo_deg + DEG_OFFSET;
    let len = geo.volume.len() as i64;
    if i0 < 0 || i1 >= len || i1 < i0 {
        return Err(format!("IVC/EVO fora da tabela: {} / {}", inp.ivc_deg, inp.evo_deg));
    }
    let (i0, i1) = (i0 as usize, i1 as usize);
    let vol = &geo.volume;
    let rpm = inp.rpm;
    let m_air = inp.m_air_kg;
    let m_fuel = if inp.lam > 0.0 { m_air / (inp.lam * inp.afr) } else { 0.0 };
    let m_tot = (m_air + m_fuel) / (1.0 - inp.x_r);
    let t_ivc = inp.t_ivc_k;
    let v_ivc = vol[i0];
    let p_ivc = m_tot * R_MIX * t_ivc / v_ivc;
    let mr = m_tot * R_MIX;
    let q_avail = if m_fuel > 0.0 { py_min(m_fuel, m_air / inp.afr) * inp.lhv_j_kg } else { 0.0 };
    let q_tot = if inp.fire { COMBUSTION_EFFICIENCY * q_avail } else { 0.0 };
    let sp = 2.0 * geo.stroke_m * rpm / 60.0;
    let c1sp = WOSCHNI_C1 * sp;
    let dt_deg = 1.0 / (6.0 * rpm);
    let hk = geo.woschni_k * dt_deg;
    let c2k = WOSCHNI_C2 * geo.vd_cyl_m3 * t_ivc / (p_ivc / 1000.0 * v_ivc) / 1000.0;
    let a_w = geo.wiebe_a;
    let m_w = geo.wiebe_m;
    let mp1 = m_w + 1.0;
    let spark = -inp.advance_deg;
    let theta0 = spark + ignition_delay_deg(rpm);
    let mut duration = -1.0_f64;
    let mut rate_k = 0.0_f64;
    let ctx = Ctx {
        vol,
        motored: motored(i0),
        c1sp_08: c1sp.powf(0.8),
        dvol: &geo.dvol,
        area: &geo.area,
        mr,
        c1sp,
        c2k,
        hk,
        p_ivc,
        t_wall: inp.t_wall_k,
    };
    let dq_comb = |theta: f64, duration: f64, rate_k: f64| -> f64 {
        if duration <= 0.0 || theta <= theta0 || theta > theta0 + duration {
            return 0.0;
        }
        let y = (theta - theta0) / duration;
        rate_k * y.powf(m_w) * (-a_w * y.powf(mp1)).exp()
    };

    let n = i1 - i0 + 1;
    let mut pres = vec![0.0_f64; n];
    let mut temp = vec![0.0_f64; n];
    pres[0] = p_ivc;
    temp[0] = t_ivc;
    let mut p = p_ivc;
    let mut work = 0.0_f64;
    let mut q_wall = 0.0_f64;
    let mut q_comb = 0.0_f64;
    let mut w_abs = 0.0_f64;
    let mut comb = false;
    let mut dqc0 = 0.0_f64;
    for k in 0..n - 1 {
        let i = i0 + k;
        let th1 = (i as i64 + 1 - DEG_OFFSET) as f64;
        if duration < 0.0 && th1 >= spark {
            let t_now = p * vol[i] / mr;
            let lam_eff = if inp.lam > 0.0 { inp.lam } else { 1.0 };
            duration = burn_duration_deg(
                rpm,
                lam_eff,
                inp.flame,
                inp.x_r,
                t_now,
                p / 1000.0,
                geo.duration_ref_deg,
                geo.rpm_ref,
            );
            rate_k = q_tot * a_w * mp1 / duration;
        }
        let (f1, dqw1) = ctx.deriv(i, p, dqc0, comb);
        let mut p_pred = p + f1;
        if p_pred <= 0.0 {
            p_pred = p * 0.5;
        }
        comb = comb || (duration > 0.0 && th1 > theta0);
        let dqc1 = dq_comb(th1, duration, rate_k);
        let (f2, dqw2) = ctx.deriv(i + 1, p_pred, dqc1, comb);
        let p_new = p + 0.5 * (f1 + f2);
        let dv = vol[i + 1] - vol[i];
        let dw = 0.5 * (p + p_new) * dv;
        work += dw;
        w_abs += dw.abs();
        q_wall += 0.5 * (dqw1 + dqw2);
        q_comb += 0.5 * (dqc0 + dqc1);
        p = p_new;
        pres[k + 1] = p;
        temp[k + 1] = p * vol[i + 1] / mr;
        dqc0 = dqc1;
    }

    if duration < 0.0 {
        duration = burn_duration_deg(
            rpm,
            1.0,
            inp.flame,
            inp.x_r,
            t_ivc,
            p_ivc / 1000.0,
            geo.duration_ref_deg,
            geo.rpm_ref,
        );
    }
    let t_evo = temp[n - 1];
    let du = m_tot * (internal_energy_per_kg(t_evo) - internal_energy_per_kg(t_ivc));
    let reference = if q_comb > 0.0 { q_comb } else { py_max(w_abs, 1e-9) };
    let energy_error = (q_comb - work - q_wall - du).abs() / reference;

    let mut k_max = 0usize;
    for (k, &pk) in pres.iter().enumerate().skip(1) {
        if pk > pres[k_max] {
            k_max = k;
        }
    }
    let mut theta_pk = (k_max as i64 + inp.ivc_deg) as f64;
    if 0 < k_max && k_max < n - 1 {
        let (pa, pb, pc) = (pres[k_max - 1], pres[k_max], pres[k_max + 1]);
        let denom = pa - 2.0 * pb + pc;
        if denom < 0.0 {
            theta_pk += 0.5 * (pa - pc) / denom;
        }
    }
    let xb_evo =
        if inp.fire { wiebe_fraction(inp.evo_deg as f64, theta0, duration, a_w, m_w) } else { 0.0 };
    let unburned = m_fuel * inp.lhv_j_kg - q_comb;

    let start = (spark.ceil() as i64).max(inp.ivc_deg);
    let mut end = ((theta0 + duration).ceil() as i64).min(inp.evo_deg);
    end = end.max(start);
    let mut ev_p = Vec::new();
    let mut ev_tu = Vec::new();
    let mut ev_xb = Vec::new();
    let mut g_u = gamma_of_t(t_ivc);
    let mut tu_max = t_ivc;
    for (k, &pk) in pres.iter().enumerate() {
        let theta = k as i64 + inp.ivc_deg;
        let tu = t_ivc * (pk / p_ivc).powf((g_u - 1.0) / g_u);
        g_u = gamma_of_t(tu);
        if theta >= start {
            if theta > end {
                break;
            }
            ev_p.push(pk / 1000.0);
            ev_tu.push(tu);
            ev_xb.push(if inp.fire {
                wiebe_fraction(theta as f64, theta0, duration, a_w, m_w)
            } else {
                0.0
            });
            tu_max = py_max(tu_max, tu);
        }
    }
    Ok(CycleOutput {
        p_max_pa: pres[k_max],
        p_evo_pa: pres[n - 1],
        pressure_pa: pres,
        temperature_k: temp,
        m_total_kg: m_tot,
        m_fuel_kg: m_fuel,
        q_available_j: q_avail,
        q_comb_j: q_comb,
        q_wall_j: q_wall,
        work_j: work,
        du_j: du,
        energy_error,
        theta_pmax_deg: theta_pk,
        t_evo_k: t_evo,
        xb_evo,
        burn_duration_deg: duration,
        theta0_deg: theta0,
        spark_deg: spark,
        unburned_chem_j: py_max(unburned, 0.0),
        event_theta_start: start,
        event_pressure_kpa: ev_p,
        event_t_unburned_k: ev_tu,
        event_burned_fraction: ev_xb,
        t_unburned_max_k: tu_max,
    })
}
