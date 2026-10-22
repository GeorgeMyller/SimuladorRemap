//! Submódulo `cycle`: kernels da física do motor (trilha RB da feature 003).
//!
//! - `CycleKernel`: ciclo fechado Otto de zona única (Wiebe, Woschni, γ(T), fração queimada);
//! - `GasKernel`: um tick do bloco de gás (VE física, borboleta, compressor/turbina e eixo do
//!   turbo, supercharger, intercooler e Euler linearmente implícito das pressões).
//!
//! Granularidade FFI (D-03): uma chamada por evento de combustão (só em falha da cache) e uma
//! chamada por tick para o gás. O Python em `simremap.physics` é a referência (paridade rel 1e-9).

mod gas;
mod interp;
mod solver;
mod thermal;

use pyo3::exceptions::{PyValueError, PyZeroDivisionError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyTuple};
use std::sync::Mutex;

use gas::{
    Compressor, GasCommand, GasConfig, GasModel, GasState, Induction, Intercooler, Overlap,
    Supercharger, Turbo, VeModel,
};
use interp::{Interp1, Interp2};
use solver::{CycleGeometry, CycleInputs, Flame};

// ------------------------------------------------------------------ CycleKernel
/// Solver do ciclo fechado com a geometria de um motor.
#[pyclass(module = "simremap_rs._native.cycle", frozen)]
pub struct CycleKernel {
    geo: CycleGeometry,
    /// Tabela `(V_ivc/V)^1,3` do último IVC (determinística: só depende do IVC).
    motored: Mutex<(usize, Vec<f64>)>,
}

#[pymethods]
impl CycleKernel {
    #[new]
    #[pyo3(signature = (volume, dvol, wall_area, stroke_m, vd_cyl_m3, woschni_k, wiebe_a, wiebe_m, duration_ref_deg, rpm_ref))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        volume: Vec<f64>,
        dvol: Vec<f64>,
        wall_area: Vec<f64>,
        stroke_m: f64,
        vd_cyl_m3: f64,
        woschni_k: f64,
        wiebe_a: f64,
        wiebe_m: f64,
        duration_ref_deg: f64,
        rpm_ref: f64,
    ) -> PyResult<Self> {
        if volume.len() != dvol.len() || volume.len() != wall_area.len() || volume.is_empty() {
            return Err(PyValueError::new_err("tabelas angulares com tamanhos diferentes"));
        }
        Ok(Self {
            motored: Mutex::new((usize::MAX, Vec::new())),
            geo: CycleGeometry {
                volume,
                dvol,
                area: wall_area,
                stroke_m,
                vd_cyl_m3,
                woschni_k,
                wiebe_a,
                wiebe_m,
                duration_ref_deg,
                rpm_ref,
            },
        })
    }

    /// Resolve um ciclo; devolve os campos de `CycleResult` depois de `inputs`, pela ordem.
    #[pyo3(signature = (rpm, m_air_kg, lam, x_r, t_ivc_k, advance_deg, ivc_deg, evo_deg, t_wall_k, fire, afr, lhv_j_kg, b_m, b_phi, phi_m))]
    #[allow(clippy::too_many_arguments)]
    fn solve<'py>(
        &self,
        py: Python<'py>,
        rpm: f64,
        m_air_kg: f64,
        lam: f64,
        x_r: f64,
        t_ivc_k: f64,
        advance_deg: f64,
        ivc_deg: i64,
        evo_deg: i64,
        t_wall_k: f64,
        fire: bool,
        afr: f64,
        lhv_j_kg: f64,
        b_m: f64,
        b_phi: f64,
        phi_m: f64,
    ) -> PyResult<Bound<'py, PyTuple>> {
        let inp = CycleInputs {
            rpm,
            m_air_kg,
            lam,
            x_r,
            t_ivc_k,
            advance_deg,
            ivc_deg,
            evo_deg,
            t_wall_k,
            fire,
            afr,
            lhv_j_kg,
            flame: Flame { b_m, b_phi, phi_m },
        };
        let mut cache = self.motored.lock().map_err(|_| PyValueError::new_err("cache envenenada"))?;
        let geo = &self.geo;
        let o = solver::solve(geo, &inp, |i0| {
            if cache.0 != i0 {
                *cache = (i0, solver::motored_table(&geo.volume, i0));
            }
            &cache.1
        })
        .map_err(PyValueError::new_err)?;
        drop(cache);
        let items: Vec<PyObject> = vec![
            PyTuple::new(py, &o.pressure_pa)?.into_any().unbind(),
            PyTuple::new(py, &o.temperature_k)?.into_any().unbind(),
            o.m_total_kg.into_pyobject(py)?.into_any().unbind(),
            o.m_fuel_kg.into_pyobject(py)?.into_any().unbind(),
            o.q_available_j.into_pyobject(py)?.into_any().unbind(),
            o.q_comb_j.into_pyobject(py)?.into_any().unbind(),
            o.q_wall_j.into_pyobject(py)?.into_any().unbind(),
            o.work_j.into_pyobject(py)?.into_any().unbind(),
            o.du_j.into_pyobject(py)?.into_any().unbind(),
            o.energy_error.into_pyobject(py)?.into_any().unbind(),
            o.p_max_pa.into_pyobject(py)?.into_any().unbind(),
            o.theta_pmax_deg.into_pyobject(py)?.into_any().unbind(),
            o.t_evo_k.into_pyobject(py)?.into_any().unbind(),
            o.p_evo_pa.into_pyobject(py)?.into_any().unbind(),
            o.xb_evo.into_pyobject(py)?.into_any().unbind(),
            o.burn_duration_deg.into_pyobject(py)?.into_any().unbind(),
            o.theta0_deg.into_pyobject(py)?.into_any().unbind(),
            o.spark_deg.into_pyobject(py)?.into_any().unbind(),
            o.unburned_chem_j.into_pyobject(py)?.into_any().unbind(),
            o.event_theta_start.into_pyobject(py)?.into_any().unbind(),
            PyTuple::new(py, &o.event_pressure_kpa)?.into_any().unbind(),
            PyTuple::new(py, &o.event_t_unburned_k)?.into_any().unbind(),
            PyTuple::new(py, &o.event_burned_fraction)?.into_any().unbind(),
            o.t_unburned_max_k.into_pyobject(py)?.into_any().unbind(),
        ];
        PyTuple::new(py, items)
    }
}

// ------------------------------------------------------------------ GasKernel
fn req<'py, T: FromPyObject<'py>>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<T> {
    match d.get_item(key)? {
        Some(v) => v.extract::<T>(),
        None => Err(PyValueError::new_err(format!("GasKernel: campo ausente '{key}'"))),
    }
}

fn sub<'py>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<Option<Bound<'py, PyDict>>> {
    match d.get_item(key)? {
        Some(v) if !v.is_none() => Ok(Some(v.downcast_into::<PyDict>()?)),
        _ => Ok(None),
    }
}

fn interp1(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Interp1> {
    let g = sub(d, key)?.ok_or_else(|| PyValueError::new_err(format!("tabela '{key}' ausente")))?;
    Interp1::new(req(&g, "x")?, req(&g, "y")?).map_err(PyValueError::new_err)
}

fn interp2(g: &Bound<'_, PyDict>) -> PyResult<Interp2> {
    Interp2::new(req(g, "x")?, req(g, "y")?, req(g, "z")?).map_err(PyValueError::new_err)
}

fn opt_interp2(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<Interp2>> {
    sub(d, key)?.map(|g| interp2(&g)).transpose()
}

fn parse_config(d: &Bound<'_, PyDict>) -> PyResult<GasConfig> {
    let induction = match req::<String>(d, "induction")?.as_str() {
        "natural" => Induction::Natural,
        "turbo" => Induction::Turbo,
        "supercharger" => Induction::Supercharger,
        other => return Err(PyValueError::new_err(format!("indução desconhecida: {other}"))),
    };
    let ve_d = sub(d, "ve")?.ok_or_else(|| PyValueError::new_err("'ve' ausente"))?;
    let overlap = match sub(&ve_d, "overlap")? {
        Some(o) => {
            let ref_rpm: Vec<f64> = req(&o, "ref_rpm")?;
            let ref_overlap: Vec<f64> = req(&o, "ref_overlap")?;
            if ref_rpm.is_empty() || ref_rpm.len() != ref_overlap.len() {
                return Err(PyValueError::new_err("overlap de referência inválido"));
            }
            Some(Overlap { base_deg: req(&o, "base_deg")?, ref_rpm, ref_overlap })
        }
        None => None,
    };
    let ve = VeModel {
        map: interp2(
            &sub(&ve_d, "map")?.ok_or_else(|| PyValueError::new_err("'ve.map' ausente"))?,
        )?,
        rc: req(&ve_d, "rc")?,
        k_vvt: req(&ve_d, "k_vvt")?,
        g_vvt: opt_interp2(&ve_d, "g_vvt")?,
        overlap,
    };
    let turbo = match sub(d, "turbo")? {
        Some(t) => {
            let c = sub(&t, "compressor")?
                .ok_or_else(|| PyValueError::new_err("'turbo.compressor' ausente"))?;
            Some(Turbo {
                compressor: Compressor {
                    m_choke_max: req(&c, "m_choke_max_kg_s")?,
                    n_max: req(&c, "n_max_rpm")?,
                    n_design: req(&c, "n_design_rpm")?,
                    pr_design: req(&c, "pr_design")?,
                    eta_max: req(&c, "eta_max")?,
                    k1: req(&c, "k1")?,
                    k2: req(&c, "k2")?,
                    m_peak: req(&c, "m_peak_kg_s")?,
                    m_range: req(&c, "m_range_kg_s")?,
                    n_peak: req(&c, "n_peak_rpm")?,
                    table: opt_interp2(&c, "table")?,
                },
                area_m2: req(&t, "area_m2")?,
                wg_area_max_m2: req(&t, "wg_area_max_m2")?,
                eta: interp1(&t, "eta")?,
                blow_off_valve: req(&t, "blow_off_valve")?,
                inertia: req(&t, "inertia")?,
                friction_k: req(&t, "friction_k")?,
                comp_passive_area: req(&t, "comp_passive_area")?,
            })
        }
        None => None,
    };
    let sc = match sub(d, "sc")? {
        Some(s) => Some(Supercharger {
            disp_m3: req(&s, "disp_m3")?,
            pulley_ratio: req(&s, "pulley_ratio")?,
            k_leak: req(&s, "k_leak")?,
            n_ref_rpm: req(&s, "n_ref_rpm")?,
            mech_efficiency: req(&s, "mech_efficiency")?,
            eta_ad: interp1(&s, "eta_ad")?,
            bypass_valve: req(&s, "bypass_valve")?,
        }),
        None => None,
    };
    if induction == Induction::Turbo && turbo.is_none() {
        return Err(PyValueError::new_err("turbo sem compressor/turbina"));
    }
    if induction == Induction::Supercharger && sc.is_none() {
        return Err(PyValueError::new_err("supercharger ausente"));
    }
    let n_substeps: usize = req(d, "n_substeps")?;
    if n_substeps == 0 {
        return Err(PyValueError::new_err("n_substeps deve ser ≥ 1"));
    }
    Ok(GasConfig {
        induction,
        pre_compressor: req(d, "pre_compressor")?,
        has_boost_volume: req(d, "has_boost_volume")?,
        v_boost: req(d, "v_boost")?,
        v_man: req(d, "v_man")?,
        v_exh: req(d, "v_exh")?,
        throttle_d: req(d, "throttle_d")?,
        vd_total_m3: req(d, "vd_total_m3")?,
        exh_backpressure_kpa: req(d, "exh_backpressure_kpa")?,
        exh_ref_flow: req(d, "exh_ref_flow")?,
        na_exhaust_area: req(d, "na_exhaust_area")?,
        n_substeps,
        h: req(d, "h")?,
        ve,
        turbo,
        sc,
        ic: Intercooler {
            present: req(d, "ic_present")?,
            effectiveness: req(d, "ic_effectiveness")?,
            k_dp: req(d, "ic_k_dp")?,
        },
    })
}

/// Bloco de gás de um motor (configuração fixa; o estado vem do `EngineVars` em cada tick).
#[pyclass(module = "simremap_rs._native.cycle", frozen)]
pub struct GasKernel {
    model: GasModel,
}

const STATE_LEN: usize = 21;

#[pymethods]
impl GasKernel {
    #[new]
    fn new(config: &Bound<'_, PyDict>) -> PyResult<Self> {
        Ok(Self { model: GasModel::new(parse_config(config)?) })
    }

    /// VE física (`TrueVolumetricEfficiency.__call__`).
    fn ve(&self, rpm: f64, map_kpa: f64, p_exh_kpa: f64, vvt_deg: f64, vvt_ex_deg: f64) -> f64 {
        self.model.ve(rpm, map_kpa, p_exh_kpa, vvt_deg, vvt_ex_deg)
    }

    /// Um tick do gás. `state` segue `GAS_STATE_FIELDS`; devolve 11 estados + 15 diagnósticos.
    fn step<'py>(
        &self,
        py: Python<'py>,
        state: Vec<f64>,
        bypass_open: bool,
        antilag_air_pct: f64,
        leak: f64,
    ) -> PyResult<Bound<'py, PyTuple>> {
        if state.len() != STATE_LEN {
            return Err(PyValueError::new_err(format!(
                "estado do gás com {} campos (esperado {STATE_LEN})",
                state.len()
            )));
        }
        let s = &state;
        let mut v = GasState {
            p_amb: s[0],
            t_amb: s[1],
            fan: s[2],
            rpm: s[3],
            throttle_pct: s[4],
            vvt_in: s[5],
            vvt_ex: s[6],
            wastegate_x: s[7],
            fuel_rate: s[8],
            egt_col: s[9],
            p_boost: s[10],
            p_man: s[11],
            p_exh: s[12],
            t_boost: s[13],
            t_man: s[14],
            turbo_omega: s[15],
            ic_core: s[16],
            m_comp: s[17],
            m_exh_out: s[18],
            surge_s: s[19],
            m_throttle_cum: s[20],
        };
        let cmd = GasCommand { bypass_open, antilag_air_pct, leak };
        let d = self.model.step(&mut v, &cmd).map_err(PyZeroDivisionError::new_err)?;
        PyTuple::new(
            py,
            [
                v.p_boost,
                v.p_man,
                v.p_exh,
                v.turbo_omega,
                v.surge_s,
                v.ic_core,
                v.t_boost,
                v.t_man,
                v.m_comp,
                v.m_exh_out,
                v.m_throttle_cum,
                d.m_thr,
                d.m_comp,
                d.m_eng,
                d.m_turb,
                d.m_wg,
                d.m_out,
                d.p_turb_w,
                d.p_comp_w,
                d.t_comp_out_k,
                d.pr_comp,
                d.eta_comp,
                d.surge_margin,
                d.sc_power_kw,
                d.sc_rpm,
                d.ve,
            ],
        )
    }
}

// ------------------------------------------------------------------ ThermalKernel
/// Fecho térmico do tick (ECT, óleo, EGT por cilindro e coletor, termopares, pistão, ponto quente).
#[pyclass(module = "simremap_rs._native.cycle", frozen)]
pub struct ThermalKernel {
    cfg: thermal::ThermalConfig,
}

#[pymethods]
impl ThermalKernel {
    #[new]
    fn new(n_cyl: usize, exh_ua_w_k: f64, egt_backpressure_factor: f64, tau_tc: f64) -> PyResult<Self> {
        if n_cyl == 0 {
            return Err(PyValueError::new_err("n_cyl deve ser ≥ 1"));
        }
        Ok(Self { cfg: thermal::ThermalConfig { n_cyl, exh_ua_w_k, egt_backpressure_factor, tau_tc } })
    }

    /// Devolve `(ect_c, oil_c, egt_col_k, tc_col_c, egt_gas_k, tc_egt_c, piston_c, hot_spot_c, egt_probe_k)`.
    #[pyo3(signature = (running, rpm, dt, imep, t_amb_k, fan_m_s, ect_c, oil_c, egt_col_k, tc_col_c, qwall_last, m_air_last, m_fuel_last, port_k_last, fire_last, egt_gas_k, tc_egt_c, piston_c, hot_spot_c))]
    #[allow(clippy::too_many_arguments)]
    fn step<'py>(
        &self,
        py: Python<'py>,
        running: bool,
        rpm: f64,
        dt: f64,
        imep: f64,
        t_amb_k: f64,
        fan_m_s: f64,
        ect_c: f64,
        oil_c: f64,
        egt_col_k: f64,
        tc_col_c: f64,
        qwall_last: Vec<f64>,
        m_air_last: Vec<f64>,
        m_fuel_last: Vec<f64>,
        port_k_last: Vec<f64>,
        fire_last: Vec<f64>,
        mut egt_gas_k: Vec<f64>,
        mut tc_egt_c: Vec<f64>,
        mut piston_c: Vec<f64>,
        mut hot_spot_c: Vec<f64>,
    ) -> PyResult<Bound<'py, PyTuple>> {
        let n = self.cfg.n_cyl;
        let lens = [
            qwall_last.len(),
            m_air_last.len(),
            m_fuel_last.len(),
            port_k_last.len(),
            fire_last.len(),
            egt_gas_k.len(),
            tc_egt_c.len(),
            piston_c.len(),
            hot_spot_c.len(),
        ];
        if lens.iter().any(|&l| l != n) {
            return Err(PyValueError::new_err(format!("vetores por cilindro devem ter {n} elementos")));
        }
        let mut probe = vec![0.0_f64; n];
        let scalars = thermal::ThermalScalars {
            running,
            rpm,
            dt,
            imep,
            t_amb_k,
            fan: fan_m_s,
            ect_c,
            oil_c,
            egt_col_k,
            tc_col_c,
        };
        let (ect, oil, egt_col, tc_col) = thermal::step(
            &self.cfg,
            &scalars,
            thermal::ThermalCylinders {
                qwall_last: &qwall_last,
                m_air_last: &m_air_last,
                m_fuel_last: &m_fuel_last,
                port_k_last: &port_k_last,
                fire_last: &fire_last,
                egt_gas: &mut egt_gas_k,
                tc_egt: &mut tc_egt_c,
                piston: &mut piston_c,
                hot_spot: &mut hot_spot_c,
                egt_probe: &mut probe,
            },
        );
        let items: Vec<PyObject> = vec![
            ect.into_pyobject(py)?.into_any().unbind(),
            oil.into_pyobject(py)?.into_any().unbind(),
            egt_col.into_pyobject(py)?.into_any().unbind(),
            tc_col.into_pyobject(py)?.into_any().unbind(),
            egt_gas_k.into_pyobject(py)?.into_any().unbind(),
            tc_egt_c.into_pyobject(py)?.into_any().unbind(),
            piston_c.into_pyobject(py)?.into_any().unbind(),
            hot_spot_c.into_pyobject(py)?.into_any().unbind(),
            probe.into_pyobject(py)?.into_any().unbind(),
        ];
        PyTuple::new(py, items)
    }
}

// ------------------------------------------------------------------ funções soltas
/// `math.fsum` (Shewchuk do CPython), exposto para a paridade.
#[pyfunction]
fn fsum(values: Vec<f64>) -> f64 {
    thermal::fsum(values)
}

/// `gamma_of_t` (paridade do solver).
#[pyfunction]
fn gamma_of_t(t_k: f64) -> f64 {
    solver::gamma_of_t(t_k)
}

/// `internal_energy_per_kg` (paridade do solver).
#[pyfunction]
fn internal_energy_per_kg(t_k: f64) -> f64 {
    solver::internal_energy_per_kg(t_k)
}

/// `burn_duration_deg` (paridade da combustão).
#[pyfunction]
#[pyo3(signature = (rpm, lam, b_m, b_phi, phi_m, x_r, t_u_k, p_kpa, duration_ref_deg=55.0, rpm_ref=3000.0))]
#[allow(clippy::too_many_arguments)]
fn burn_duration_deg(
    rpm: f64,
    lam: f64,
    b_m: f64,
    b_phi: f64,
    phi_m: f64,
    x_r: f64,
    t_u_k: f64,
    p_kpa: f64,
    duration_ref_deg: f64,
    rpm_ref: f64,
) -> f64 {
    solver::burn_duration_deg(rpm, lam, Flame { b_m, b_phi, phi_m }, x_r, t_u_k, p_kpa, duration_ref_deg, rpm_ref)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CycleKernel>()?;
    m.add_class::<GasKernel>()?;
    m.add_class::<ThermalKernel>()?;
    m.add_function(wrap_pyfunction!(fsum, m)?)?;
    m.add_function(wrap_pyfunction!(gamma_of_t, m)?)?;
    m.add_function(wrap_pyfunction!(internal_energy_per_kg, m)?)?;
    m.add_function(wrap_pyfunction!(burn_duration_deg, m)?)?;
    m.add("GAS_STATE_LEN", STATE_LEN)?;
    Ok(())
}
