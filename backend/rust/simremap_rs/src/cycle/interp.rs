//! Interpolação 1D/2D com saturação (espelho de `simremap.physics.interp`).
//!
//! Mesma ordem de operações do Python (`bisect_right` e fração local) para paridade exata.

/// Mínimo/máximo com a semântica do `min`/`max` embutido do Python (primeiro elemento em empate).
#[inline]
pub fn py_max(a: f64, b: f64) -> f64 {
    if b > a {
        b
    } else {
        a
    }
}

#[inline]
pub fn py_min(a: f64, b: f64) -> f64 {
    if b < a {
        b
    } else {
        a
    }
}

/// `bisect.bisect_right(axis, x)`.
#[inline]
pub fn bisect_right(axis: &[f64], x: f64) -> usize {
    let (mut lo, mut hi) = (0usize, axis.len());
    while lo < hi {
        let mid = (lo + hi) / 2;
        if x < axis[mid] {
            hi = mid;
        } else {
            lo = mid + 1;
        }
    }
    lo
}

#[inline]
fn locate(axis: &[f64], x: f64) -> (usize, f64) {
    let last = axis.len() - 1;
    if x <= axis[0] {
        return (0, 0.0);
    }
    if x >= axis[last] {
        return (last - 1, 1.0);
    }
    let i = bisect_right(axis, x) - 1;
    let x0 = axis[i];
    (i, (x - x0) / (axis[i + 1] - x0))
}

#[derive(Clone, Debug)]
pub struct Interp1 {
    x: Vec<f64>,
    y: Vec<f64>,
}

impl Interp1 {
    pub fn new(x: Vec<f64>, y: Vec<f64>) -> Result<Self, String> {
        if x.len() != y.len() || x.len() < 2 {
            return Err("Interp1D exige x e y do mesmo tamanho (≥ 2)".into());
        }
        Ok(Self { x, y })
    }

    #[inline]
    pub fn eval(&self, x: f64) -> f64 {
        let (i, f) = locate(&self.x, x);
        let y0 = self.y[i];
        y0 + (self.y[i + 1] - y0) * f
    }
}

#[derive(Clone, Debug)]
pub struct Interp2 {
    x: Vec<f64>,
    y: Vec<f64>,
    z: Vec<Vec<f64>>,
}

impl Interp2 {
    pub fn new(x: Vec<f64>, y: Vec<f64>, z: Vec<Vec<f64>>) -> Result<Self, String> {
        if x.len() < 2 || y.len() < 2 || z.len() != y.len() || z.iter().any(|r| r.len() != x.len()) {
            return Err("Interp2D: z deve ter len(y) linhas × len(x) colunas".into());
        }
        Ok(Self { x, y, z })
    }

    #[inline]
    pub fn eval(&self, x: f64, y: f64) -> f64 {
        let (i, fx) = locate(&self.x, x);
        let (j, fy) = locate(&self.y, y);
        let r0 = &self.z[j];
        let r1 = &self.z[j + 1];
        let a = r0[i] + (r0[i + 1] - r0[i]) * fx;
        let b = r1[i] + (r1[i + 1] - r1[i]) * fx;
        a + (b - a) * fy
    }
}

/// `x ** 2` do Python: chama a `pow` da libm (o LLVM trocaria `powf(2.0)` por `x * x`, que
/// pode diferir 1 ulp da `pow` usada pelo CPython).
#[inline]
pub fn pw2(x: f64) -> f64 {
    x.powf(std::hint::black_box(2.0))
}
