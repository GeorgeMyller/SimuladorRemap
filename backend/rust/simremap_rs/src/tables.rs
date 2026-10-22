//! Submódulo `tables`: interpolação das tabelas da ECU e estratégias com estado.
//!
//! Reproduz `simremap.ecu.tables.interp1`/`interp2` (clamp nas bordas, sem extrapolação,
//! `bisect_right` e a mesma ordem das operações em ponto flutuante, por isso o resultado é
//! bit a bit igual ao Python). A granularidade da FFI é o lote: `TableSet.eval` avalia
//! todas as tabelas de um grupo com uma única chamada por tick.

use pyo3::exceptions::{PyIndexError, PyValueError};
use pyo3::prelude::*;

pub mod strategies;

// --------------------------------------------------------------------------- núcleo

/// Índice `i` com `axis[i] <= x < axis[i + 1]` (equivale a `bisect_right(axis, x) - 1`).
#[inline]
fn bisect_right_minus_one(axis: &[f64], x: f64) -> usize {
    axis.partition_point(|&a| a <= x) - 1
}

/// Interpolação linear com clamp nas bordas (`interp1` do Python).
#[inline]
pub fn interp1_raw(xs: &[f64], vs: &[f64], x: f64) -> f64 {
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    if !(x > xs[0]) {
        return vs[0]; // inclui NaN: vale a primeira borda
    }
    let last = xs.len() - 1;
    if x >= xs[last] {
        return vs[last];
    }
    let i = bisect_right_minus_one(xs, x);
    let x0 = xs[i];
    let v0 = vs[i];
    v0 + (x - x0) / (xs[i + 1] - x0) * (vs[i + 1] - v0)
}

/// `_locate` do Python: índice (0..n−2) e fração (0..1) com clamp.
#[inline]
fn locate(axis: &[f64], x: f64) -> (usize, f64) {
    let last = axis.len() - 1;
    #[allow(clippy::neg_cmp_op_on_partial_ord)]
    if !(x > axis[0]) {
        return (0, 0.0);
    }
    if x >= axis[last] {
        return (last - 1, 1.0);
    }
    let i = bisect_right_minus_one(axis, x);
    let x0 = axis[i];
    (i, (x - x0) / (axis[i + 1] - x0))
}

/// Interpolação bilinear com clamp; `z` em ordem de linhas (`z[i * nx + j]`, linha = y).
#[inline]
pub fn interp2_raw(xs: &[f64], ys: &[f64], z: &[f64], x: f64, y: f64) -> f64 {
    let nx = xs.len();
    let (j, fx) = locate(xs, x);
    let (i, fy) = locate(ys, y);
    let r0 = &z[i * nx..(i + 1) * nx];
    let r1 = &z[(i + 1) * nx..(i + 2) * nx];
    let a = r0[j] + fx * (r0[j + 1] - r0[j]);
    let b = r1[j] + fx * (r1[j + 1] - r1[j]);
    a + fy * (b - a)
}

fn check_axis(name: &str, axis: &[f64], min_len: usize) -> PyResult<()> {
    if axis.len() < min_len {
        return Err(PyValueError::new_err(format!(
            "eixo {name} precisa de pelo menos {min_len} pontos"
        )));
    }
    Ok(())
}

fn flatten(name: &str, rows: Vec<Vec<f64>>, nx: usize, ny: usize) -> PyResult<Vec<f64>> {
    if rows.len() != ny || rows.iter().any(|r| r.len() != nx) {
        return Err(PyValueError::new_err(format!(
            "{name}: esperado {ny} linhas × {nx} colunas"
        )));
    }
    Ok(rows.into_iter().flatten().collect())
}

// --------------------------------------------------------------------------- funções

/// `interp1(xs, vs, x)` com a semântica do Python.
#[pyfunction]
fn interp1(xs: Vec<f64>, vs: Vec<f64>, x: f64) -> PyResult<f64> {
    check_axis("x", &xs, 1)?;
    if vs.len() != xs.len() {
        return Err(PyValueError::new_err("xs e vs com tamanhos diferentes"));
    }
    Ok(interp1_raw(&xs, &vs, x))
}

/// `interp2(xs, ys, z, x, y)` com a semântica do Python (`z[linha=y][coluna=x]`).
#[pyfunction]
fn interp2(xs: Vec<f64>, ys: Vec<f64>, z: Vec<Vec<f64>>, x: f64, y: f64) -> PyResult<f64> {
    check_axis("x", &xs, 2)?;
    check_axis("y", &ys, 2)?;
    let flat = flatten("z", z, xs.len(), ys.len())?;
    Ok(interp2_raw(&xs, &ys, &flat, x, y))
}

// --------------------------------------------------------------------------- lote

enum Tab {
    One {
        qx: usize,
        xs: Vec<f64>,
        vs: Vec<f64>,
    },
    Two {
        qx: usize,
        qy: usize,
        xs: Vec<f64>,
        ys: Vec<f64>,
        z: Vec<f64>,
    },
}

impl Tab {
    #[inline]
    fn eval(&self, inputs: &[f64]) -> f64 {
        match self {
            Tab::One { qx, xs, vs } => interp1_raw(xs, vs, inputs[*qx]),
            Tab::Two { qx, qy, xs, ys, z } => interp2_raw(xs, ys, z, inputs[*qx], inputs[*qy]),
        }
    }
}

/// Grupo de tabelas compiladas avaliadas juntas sobre o vetor `inputs` do tick.
///
/// Cada especificação é `(qx, qy, xs, ys, values)`: 1D com `qy = -1`, `ys = []` e
/// `values = [vs]`; 2D com `values` em `len(ys)` linhas × `len(xs)` colunas.
#[pyclass(frozen, module = "simremap_rs._native.tables")]
pub struct TableSet {
    tabs: Vec<Tab>,
    min_inputs: usize,
}

type Spec = (usize, i64, Vec<f64>, Vec<f64>, Vec<Vec<f64>>);

#[pymethods]
impl TableSet {
    #[new]
    fn new(specs: Vec<Spec>) -> PyResult<Self> {
        let mut tabs = Vec::with_capacity(specs.len());
        let mut min_inputs = 0usize;
        for (k, (qx, qy, xs, ys, mut values)) in specs.into_iter().enumerate() {
            let name = format!("tabela {k}");
            min_inputs = min_inputs.max(qx + 1);
            if qy < 0 {
                check_axis(&name, &xs, 1)?;
                if values.len() != 1 || values[0].len() != xs.len() {
                    return Err(PyValueError::new_err(format!(
                        "{name}: 1D exige values = [vs] com len(vs) == len(xs)"
                    )));
                }
                let vs = values.pop().unwrap_or_default();
                tabs.push(Tab::One { qx, xs, vs });
            } else {
                let qy = qy as usize;
                min_inputs = min_inputs.max(qy + 1);
                check_axis(&name, &xs, 2)?;
                check_axis(&name, &ys, 2)?;
                let z = flatten(&name, values, xs.len(), ys.len())?;
                tabs.push(Tab::Two { qx, qy, xs, ys, z });
            }
        }
        Ok(Self { tabs, min_inputs })
    }

    /// Valores de todas as tabelas do grupo, na ordem das especificações.
    fn eval(&self, inputs: Vec<f64>) -> PyResult<Vec<f64>> {
        if inputs.len() < self.min_inputs {
            return Err(PyIndexError::new_err(format!(
                "inputs com {} posições; o grupo exige {}",
                inputs.len(),
                self.min_inputs
            )));
        }
        Ok(self.tabs.iter().map(|t| t.eval(&inputs)).collect())
    }

    fn __len__(&self) -> usize {
        self.tabs.len()
    }
}

// --------------------------------------------------------------------------- registo

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(interp1, m)?)?;
    m.add_function(wrap_pyfunction!(interp2, m)?)?;
    m.add_class::<TableSet>()?;
    strategies::register(m)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interp_clamps_and_interpolates() {
        let xs = [0.0, 10.0];
        let vs = [0.0, 100.0];
        assert_eq!(interp1_raw(&xs, &vs, 5.0), 50.0);
        assert_eq!(interp1_raw(&xs, &vs, -1.0), 0.0);
        assert_eq!(interp1_raw(&xs, &vs, f64::NAN), 0.0);
        assert_eq!(interp1_raw(&xs, &vs, 99.0), 100.0);
        let z = [10.0, 20.0, 30.0, 40.0];
        assert_eq!(interp2_raw(&[2000.0, 2500.0], &[50.0, 100.0], &z, 2250.0, 75.0), 25.0);
        assert_eq!(interp2_raw(&[2000.0, 2500.0], &[50.0, 100.0], &z, 9000.0, 500.0), 40.0);
    }
}
