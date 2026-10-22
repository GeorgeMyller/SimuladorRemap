//! Kernels nativos do SimuladorRemap expostos ao Python via PyO3 (ABI3, Python 3.12+).
//!
//! Cada submódulo é dono de um conjunto de kernels:
//! - `tables`: interpolação 1D/2D de tabelas, eixos e cálculos das estratégias da ECU;
//! - `cycle`: solver termodinâmico 0D/1D do ciclo Otto, turbo e compressor;
//! - `damage`: integral de detonação e acumulação de dano estrutural.

use pyo3::prelude::*;

pub mod cycle;
pub mod damage;
pub mod tables;

#[pymodule]
fn _native(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    for (name, init) in [
        ("tables", tables::register as fn(&Bound<'_, PyModule>) -> PyResult<()>),
        ("cycle", cycle::register),
        ("damage", damage::register),
    ] {
        let sub = PyModule::new(py, name)?;
        init(&sub)?;
        m.add_submodule(&sub)?;
        py.import("sys")?
            .getattr("modules")?
            .set_item(format!("simremap_rs._native.{name}"), &sub)?;
    }
    Ok(())
}
