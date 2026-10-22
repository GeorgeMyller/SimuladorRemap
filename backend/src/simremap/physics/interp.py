"""Interpoladores rápidos (listas Python + ``bisect``) para as grades do catálogo.

Interpolação linear (1D) e bilinear (2D) com saturação nas bordas, como define o
``vehicle-catalog`` para ``Grid1D`` e ``Grid2D``. Sem alocação por chamada.
"""

from __future__ import annotations

from bisect import bisect_right

from simremap.catalog.contracts import Grid1D, Grid2D

__all__ = ["Interp1D", "Interp2D"]


def _locate(axis: list[float], x: float) -> tuple[int, float]:
    """Índice da célula e fração local (0..1) com saturação nas bordas."""
    last = len(axis) - 1
    if x <= axis[0]:
        return 0, 0.0
    if x >= axis[last]:
        return last - 1, 1.0
    i = bisect_right(axis, x) - 1
    x0 = axis[i]
    return i, (x - x0) / (axis[i + 1] - x0)


class Interp1D:
    """Curva 1D ``y(x)``."""

    __slots__ = ("x", "y")

    def __init__(self, x: list[float], y: list[float]) -> None:
        if len(x) != len(y) or len(x) < 2:  # noqa: PLR2004
            raise ValueError("Interp1D exige x e y do mesmo tamanho (≥ 2)")
        self.x = [float(v) for v in x]
        self.y = [float(v) for v in y]

    @classmethod
    def from_grid(cls, grid: Grid1D) -> Interp1D:
        return cls(list(grid.x_values), list(grid.values))

    def __call__(self, x: float) -> float:
        i, f = _locate(self.x, x)
        y0 = self.y[i]
        return y0 + (self.y[i + 1] - y0) * f


class Interp2D:
    """Tabela 2D ``z(x, y)`` (linhas = y, colunas = x)."""

    __slots__ = ("x", "y", "z")

    def __init__(self, x: list[float], y: list[float], z: list[list[float]]) -> None:
        if len(z) != len(y) or any(len(row) != len(x) for row in z):
            raise ValueError("Interp2D: z deve ter len(y) linhas × len(x) colunas")
        self.x = [float(v) for v in x]
        self.y = [float(v) for v in y]
        self.z = [[float(v) for v in row] for row in z]

    @classmethod
    def from_grid(cls, grid: Grid2D) -> Interp2D:
        return cls(list(grid.x_values), list(grid.y_values), [list(r) for r in grid.z_values])

    def __call__(self, x: float, y: float) -> float:
        i, fx = _locate(self.x, x)
        j, fy = _locate(self.y, y)
        r0 = self.z[j]
        r1 = self.z[j + 1]
        a = r0[i] + (r0[i + 1] - r0[i]) * fx
        b = r1[i] + (r1[i + 1] - r1[i]) * fx
        return a + (b - a) * fy
