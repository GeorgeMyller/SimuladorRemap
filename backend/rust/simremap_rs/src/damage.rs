//! Submódulo `damage`: kernels quentes do `DamageModel` (feature 003, T012).
//!
//! - [`knock_onset`]: Douaud-Eyzat + integral de Livengood-Wu de um ciclo (RF-01 a RF-03);
//! - [`traces_finite`]: validação EC-02 dos vetores do `CombustionEvent`;
//! - [`DamageKernel`]: passo contínuo por tick (temperatura de knock, lambda pobre,
//!   temperaturas de metal das válvulas e da turbina, fluência de Larson-Miller de pistão,
//!   válvulas e turbina, bronzinas e sobrevelocidade do turbo) com a acumulação de dano
//!   escrita diretamente nos arrays NumPy do modelo (buffer protocol, sem cópia).
//!
//! A ordem das operações em ponto flutuante replica a referência Python
//! (`knock.py`, `thermal.py`, `mechanical.py`, `model.py`) para paridade bit a bit;
//! `max`/`min` seguem a semântica do `max()`/`min()` do Python (o primeiro argumento vence
//! empates e NaN no segundo argumento).

use std::cell::Cell;

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

const ATM_KPA: f64 = 101.325;
const DE_COEFF_MS: f64 = 17.68;
const DE_ON_EXP: f64 = 3.402;
const DE_P_EXP: f64 = -1.7;
const DE_ACTIVATION_K: f64 = 3800.0;
const KELVIN: f64 = 273.15;
const SECONDS_PER_HOUR: f64 = 3600.0;

// índices em `CAUSES` (failure.py): knock, thermal, overload, overrev, preignition, pressure
const CAUSE_THERMAL: usize = 1;
const CAUSE_OVERREV: usize = 3;
const N_CAUSES: usize = 6;

/// `max(a, b)` do Python: devolve `b` só se `b > a`.
#[inline]
fn py_max(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

/// `min(a, b)` do Python: devolve `b` só se `b < a`.
#[inline]
fn py_min(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

/// Douaud-Eyzat + Livengood-Wu: `(I_LW no fim, índice do 1.º ponto com I_LW ≥ 1 ou -1)`.
#[pyfunction]
#[pyo3(signature = (pressure_kpa, t_unburned_k, rpm, octane, tau_multiplier, tau_min_temp_k, tau_min_pressure_kpa, tau_saturation_ms))]
#[allow(clippy::too_many_arguments)]
fn knock_onset(
    pressure_kpa: Vec<f64>,
    t_unburned_k: Vec<f64>,
    rpm: f64,
    octane: f64,
    tau_multiplier: f64,
    tau_min_temp_k: f64,
    tau_min_pressure_kpa: f64,
    tau_saturation_ms: f64,
) -> PyResult<(f64, i64)> {
    if pressure_kpa.len() != t_unburned_k.len() {
        return Err(PyValueError::new_err(
            "pressure_kpa e t_unburned_k com comprimentos diferentes",
        ));
    }
    Ok(knock_onset_core(
        &pressure_kpa,
        &t_unburned_k,
        rpm,
        octane,
        tau_multiplier,
        tau_min_temp_k,
        tau_min_pressure_kpa,
        tau_saturation_ms,
    ))
}

#[allow(clippy::too_many_arguments)]
fn knock_onset_core(
    pressure: &[f64],
    t_unburned: &[f64],
    rpm: f64,
    octane: f64,
    tau_multiplier: f64,
    tau_min_temp_k: f64,
    tau_min_pressure_kpa: f64,
    tau_saturation_ms: f64,
) -> (f64, i64) {
    // escalar Python: ((17,68 · mult) · (ON/100)^3,402), depois · p^-1,7 · exp(...) por ponto
    let head = DE_COEFF_MS * tau_multiplier * (octane / 100.0).powf(DE_ON_EXP);
    let ms_per_deg = 1000.0 / (6.0 * rpm);
    let mut integral = 0.0_f64;
    let mut onset: i64 = -1;
    for (j, (&p, &t)) in pressure.iter().zip(t_unburned).enumerate() {
        let valid = t >= tau_min_temp_k && p >= tau_min_pressure_kpa;
        let tau = if valid {
            let p_atm = p / ATM_KPA;
            let raw = head * p_atm.powf(DE_P_EXP) * (DE_ACTIVATION_K / t).exp();
            // np.minimum (sem NaN: validate_event já rejeitou não finitos)
            if raw.is_nan() || raw < tau_saturation_ms {
                raw
            } else {
                tau_saturation_ms
            }
        } else {
            tau_saturation_ms
        };
        integral += ms_per_deg / tau;
        if onset < 0 && integral >= 1.0 {
            onset = j as i64;
        }
    }
    (integral, onset)
}

/// EC-02: `True` se os três vetores só têm valores finitos.
#[pyfunction]
fn traces_finite(a: Vec<f64>, b: Vec<f64>, c: Vec<f64>) -> bool {
    a.iter().chain(&b).chain(&c).all(|v| v.is_finite())
}

/// `LMP_ref = T_lim,K · (C + log10(t_ref_h))` (thermal.py).
fn lmp_reference(limit_c: f64, t_ref_s: f64, constant: f64) -> f64 {
    (limit_c + KELVIN) * (constant + (t_ref_s / SECONDS_PER_HOUR).log10())
}

/// `metal_temp_step` (thermal.py) com `alpha = 1 − exp(−dt/τ)` já calculado.
#[inline]
fn metal_step(previous: f64, gas: f64, alpha: f64) -> f64 {
    if previous.is_nan() {
        gas
    } else {
        previous + alpha * (gas - previous)
    }
}

#[derive(Clone, Copy)]
struct Creep {
    limit_c: f64,
    lmp: f64,
}

impl Creep {
    fn new(limit_c: f64, t_ref_s: f64, constant: f64) -> Self {
        Self {
            limit_c,
            lmp: lmp_reference(limit_c, t_ref_s, constant),
        }
    }

    /// `creep_damage` (thermal.py): `dt / t_r(T)` acima do limite, 0 no limite ou abaixo.
    #[inline]
    fn damage(&self, temp_c: f64, dt: f64, constant: f64) -> f64 {
        if !(temp_c > self.limit_c) {
            return 0.0;
        }
        let exponent = self.lmp / (temp_c + KELVIN) - constant;
        let rupture = SECONDS_PER_HOUR * 10.0_f64.powf(py_min(exponent, 300.0));
        dt / rupture
    }
}

/// Arrays do modelo (vistas mutáveis sobre os buffers NumPy).
struct Views<'a> {
    health: &'a [Cell<f64>],
    virtual_: &'a [Cell<f64>],
    causes: &'a [Cell<f64>],
    first_damage: &'a [Cell<f64>],
}

impl Views<'_> {
    /// `DamageModel._apply`.
    #[inline]
    fn apply(&self, enabled: bool, index: usize, amount: f64, cause: usize, t: f64) {
        if amount <= 0.0 {
            return;
        }
        if enabled {
            let h = &self.health[index];
            h.set(py_max(0.0, h.get() - amount));
        }
        let v = &self.virtual_[index];
        v.set(py_max(0.0, v.get() - amount));
        let c = &self.causes[index * N_CAUSES + cause];
        c.set(c.get() + amount);
        let f = &self.first_damage[index];
        if f.get().is_nan() {
            f.set(t);
        }
    }
}

fn mut_view<'a>(
    py: Python<'a>,
    buf: &'a PyBuffer<f64>,
    name: &str,
    len: usize,
) -> PyResult<&'a [Cell<f64>]> {
    let view = buf.as_mut_slice(py).ok_or_else(|| {
        PyValueError::new_err(format!("{name}: buffer float64 C-contíguo e gravável exigido"))
    })?;
    if view.len() != len {
        return Err(PyValueError::new_err(format!(
            "{name}: {} elementos (esperado {len})",
            view.len()
        )));
    }
    Ok(view)
}

/// Passo contínuo do dano ligado aos arrays de um `DamageModel` (RF-12, RF-13, RF-15, RF-16).
///
/// Os buffers ficam presos enquanto o kernel existir: o modelo recria o kernel quando
/// troca algum array (``load_snapshot``).
#[pyclass(module = "simremap_rs._native.damage")]
pub struct DamageKernel {
    n_cyl: usize,
    n_comp: usize,
    enabled: bool,
    thermal: bool,
    mechanical: bool,
    turbine_index: Option<usize>,
    bearings_index: usize,
    knock_temp_gain_c: f64,
    knock_temp_tau_s: f64,
    lean_map_min_kpa: f64,
    k_lean_c: f64,
    lambda_lean_ref: f64,
    lm_constant: f64,
    piston: Creep,
    valve: Creep,
    valve_tau_s: f64,
    turbine: Creep,
    turbine_tau_s: f64,
    max_rpm: f64,
    bearing_overrev_rate: f64,
    turbo_max_rpm: Option<f64>,
    turbo_burst_ratio: f64,
    turbo_overspeed_rate: f64,
    health: PyBuffer<f64>,
    virtual_: PyBuffer<f64>,
    causes: PyBuffer<f64>,
    first_damage: PyBuffer<f64>,
    knock_temp: PyBuffer<f64>,
    last_intensity: PyBuffer<f64>,
    valve_temp: PyBuffer<f64>,
    turbine_temp: PyBuffer<f64>,
}

#[pymethods]
impl DamageKernel {
    #[new]
    #[pyo3(signature = (
        *, health, virtual_health, causes, first_damage, knock_temp, last_intensity,
        valve_temp, turbine_temp, n_cyl, has_turbine, enabled, thermal, mechanical,
        knock_temp_gain_c, knock_temp_tau_s, lean_map_min_kpa, k_lean_c, lambda_lean_ref,
        lm_constant, piston_limit_c, piston_t_ref_s, valve_limit_c, valve_t_ref_s,
        valve_tau_s, turbine_limit_c, turbine_t_ref_s, turbine_tau_s, max_rpm,
        bearing_overrev_rate, turbo_max_rpm, turbo_burst_ratio, turbo_overspeed_rate
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        health: &Bound<'_, PyAny>,
        virtual_health: &Bound<'_, PyAny>,
        causes: &Bound<'_, PyAny>,
        first_damage: &Bound<'_, PyAny>,
        knock_temp: &Bound<'_, PyAny>,
        last_intensity: &Bound<'_, PyAny>,
        valve_temp: &Bound<'_, PyAny>,
        turbine_temp: &Bound<'_, PyAny>,
        n_cyl: usize,
        has_turbine: bool,
        enabled: bool,
        thermal: bool,
        mechanical: bool,
        knock_temp_gain_c: f64,
        knock_temp_tau_s: f64,
        lean_map_min_kpa: f64,
        k_lean_c: f64,
        lambda_lean_ref: f64,
        lm_constant: f64,
        piston_limit_c: f64,
        piston_t_ref_s: f64,
        valve_limit_c: f64,
        valve_t_ref_s: f64,
        valve_tau_s: f64,
        turbine_limit_c: f64,
        turbine_t_ref_s: f64,
        turbine_tau_s: f64,
        max_rpm: f64,
        bearing_overrev_rate: f64,
        turbo_max_rpm: Option<f64>,
        turbo_burst_ratio: f64,
        turbo_overspeed_rate: f64,
    ) -> PyResult<Self> {
        let n_comp = 3 * n_cyl + 2 + usize::from(has_turbine);
        let kernel = Self {
            n_cyl,
            n_comp,
            enabled,
            thermal,
            mechanical,
            turbine_index: has_turbine.then_some(3 * n_cyl + 2),
            bearings_index: 3 * n_cyl + 1,
            knock_temp_gain_c,
            knock_temp_tau_s,
            lean_map_min_kpa,
            k_lean_c,
            lambda_lean_ref,
            lm_constant,
            piston: Creep::new(piston_limit_c, piston_t_ref_s, lm_constant),
            valve: Creep::new(valve_limit_c, valve_t_ref_s, lm_constant),
            valve_tau_s,
            turbine: Creep::new(turbine_limit_c, turbine_t_ref_s, lm_constant),
            turbine_tau_s,
            max_rpm,
            bearing_overrev_rate,
            turbo_max_rpm,
            turbo_burst_ratio,
            turbo_overspeed_rate,
            health: PyBuffer::get(health)?,
            virtual_: PyBuffer::get(virtual_health)?,
            causes: PyBuffer::get(causes)?,
            first_damage: PyBuffer::get(first_damage)?,
            knock_temp: PyBuffer::get(knock_temp)?,
            last_intensity: PyBuffer::get(last_intensity)?,
            valve_temp: PyBuffer::get(valve_temp)?,
            turbine_temp: PyBuffer::get(turbine_temp)?,
        };
        kernel.views(py)?;
        Ok(kernel)
    }

    /// Avança um tick. Devolve ``(piston_eff_c, índices tocados, burst do turbo)``; o
    /// ``_force`` do burst fica no Python (é o último passo, como na referência).
    #[pyo3(signature = (piston_temp_c, lambda_cyl, egt_c, map_kpa, egt_collector_c, rpm, turbo_rpm, t, dt))]
    #[allow(clippy::too_many_arguments)]
    fn continuous(
        &self,
        py: Python<'_>,
        piston_temp_c: Vec<f64>,
        lambda_cyl: Vec<Option<f64>>,
        egt_c: Vec<f64>,
        map_kpa: f64,
        egt_collector_c: f64,
        rpm: f64,
        turbo_rpm: Option<f64>,
        t: f64,
        dt: f64,
    ) -> PyResult<(Vec<f64>, Vec<usize>, bool)> {
        let n = self.n_cyl;
        if piston_temp_c.len() != n || lambda_cyl.len() != n || egt_c.len() != n {
            return Err(PyValueError::new_err("listas por cilindro sem n_cyl valores"));
        }
        let (views, knock_temp, last_intensity, valve_temp, turbine_temp) = self.views(py)?;
        let mut touched: Vec<usize> = Vec::new();
        let mut apply = |index: usize, amount: f64, cause: usize| {
            // os chamadores Python só aplicam com `dano > 0` (NaN não aplica)
            if amount > 0.0 {
                views.apply(self.enabled, index, amount, cause, t);
                touched.push(index);
            }
        };
        let c = self.lm_constant;
        let knock_alpha = 1.0 - (-dt / self.knock_temp_tau_s).exp();
        let valve_alpha = 1.0 - (-dt / self.valve_tau_s).exp();
        let mut piston_eff = Vec::with_capacity(n);
        for i in 0..n {
            let lean = if self.thermal {
                let previous = knock_temp[i].get();
                let target =
                    self.knock_temp_gain_c * py_max(0.0, last_intensity[i].get() - 1.0);
                knock_temp[i].set(previous + knock_alpha * (target - previous));
                match lambda_cyl[i] {
                    Some(lam) if !(map_kpa < self.lean_map_min_kpa) => {
                        self.k_lean_c * py_max(0.0, lam - self.lambda_lean_ref)
                    }
                    _ => 0.0,
                }
            } else {
                0.0
            };
            let t_eff = piston_temp_c[i] + knock_temp[i].get() + lean;
            piston_eff.push(t_eff);
            if !self.thermal {
                continue;
            }
            apply(i, self.piston.damage(t_eff, dt, c), CAUSE_THERMAL);
            let mut previous = valve_temp[i].get();
            if previous.is_nan() {
                previous = py_min(egt_c[i], egt_collector_c);
            }
            let valve_t = metal_step(previous, egt_c[i], valve_alpha);
            valve_temp[i].set(valve_t);
            apply(2 * n + i, self.valve.damage(valve_t, dt, c), CAUSE_THERMAL);
        }
        if let (true, Some(turbine)) = (self.thermal, self.turbine_index) {
            let alpha = 1.0 - (-dt / self.turbine_tau_s).exp();
            let turbine_t = metal_step(turbine_temp[0].get(), egt_collector_c, alpha);
            turbine_temp[0].set(turbine_t);
            apply(turbine, self.turbine.damage(turbine_t, dt, c), CAUSE_THERMAL);
        }
        let mut burst = false;
        if self.mechanical {
            if rpm > self.max_rpm {
                let rate = self.bearing_overrev_rate * (rpm / self.max_rpm - 1.0);
                if rate > 0.0 {
                    apply(self.bearings_index, rate * dt, CAUSE_OVERREV);
                }
            }
            if let (Some(turbine), Some(max), Some(turbo)) =
                (self.turbine_index, self.turbo_max_rpm, turbo_rpm)
            {
                let ratio = turbo / max;
                if ratio >= self.turbo_burst_ratio {
                    burst = true;
                } else if !(ratio <= 1.0) {
                    let rate = self.turbo_overspeed_rate * (ratio - 1.0);
                    if rate > 0.0 {
                        apply(turbine, rate * dt, CAUSE_OVERREV);
                    }
                }
            }
        }
        Ok((piston_eff, touched, burst))
    }

    #[getter]
    fn n_cyl(&self) -> usize {
        self.n_cyl
    }
}

type ViewSet<'a> = (
    Views<'a>,
    &'a [Cell<f64>],
    &'a [Cell<f64>],
    &'a [Cell<f64>],
    &'a [Cell<f64>],
);

impl DamageKernel {
    fn views<'a>(&'a self, py: Python<'a>) -> PyResult<ViewSet<'a>> {
        let n = self.n_cyl;
        let m = self.n_comp;
        Ok((
            Views {
                health: mut_view(py, &self.health, "health", m)?,
                virtual_: mut_view(py, &self.virtual_, "virtual_health", m)?,
                causes: mut_view(py, &self.causes, "causes", m * N_CAUSES)?,
                first_damage: mut_view(py, &self.first_damage, "first_damage", m)?,
            },
            mut_view(py, &self.knock_temp, "knock_temp", n)?,
            mut_view(py, &self.last_intensity, "last_intensity", n)?,
            mut_view(py, &self.valve_temp, "valve_temp", n)?,
            mut_view(py, &self.turbine_temp, "turbine_temp", 1)?,
        ))
    }
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(knock_onset, m)?)?;
    m.add_function(wrap_pyfunction!(traces_finite, m)?)?;
    m.add_class::<DamageKernel>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn onset_saturated_never_knocks() {
        let p = vec![100.0; 50];
        let t = vec![300.0; 50];
        let (end, k) = knock_onset_core(&p, &t, 3000.0, 90.0, 1.0, 600.0, 200.0, 100.0);
        assert_eq!(k, -1);
        assert!((end - 50.0 * (1000.0 / 18000.0) / 100.0).abs() < 1e-12);
    }

    #[test]
    fn creep_zero_at_limit() {
        let creep = Creep::new(950.0, 3600.0, 20.0);
        assert_eq!(creep.damage(950.0, 1e-3, 20.0), 0.0);
        assert!(creep.damage(1000.0, 1e-3, 20.0) > 0.0);
    }
}
