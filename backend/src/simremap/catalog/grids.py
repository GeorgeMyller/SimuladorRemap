"""Grelhas físicas do catálogo e interpolação (vehicle-catalog RF-10).

``Grid1D`` e ``Grid2D`` são os contratos de ``catalog/contracts.py`` (validação de eixos,
dimensões e finitude). Este módulo acrescenta a interpolação pura, sem extrapolação:
fora dos eixos o valor satura na borda (mesmo algoritmo do Apêndice B do ecu-core).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence

from simremap.catalog.contracts import Grid1D, Grid2D

__all__ = ["Grid1D", "Grid2D", "interp1d", "interp2d", "interp_linear"]


def _locate(xs: Sequence[float], x: float) -> tuple[int, float]:
    """Índice ``i`` (0..n−2) e fração ``f`` (0..1) de ``x`` saturado em ``xs``."""
    x_c = min(max(x, xs[0]), xs[-1])
    i = min(max(bisect_right(xs, x_c) - 1, 0), len(xs) - 2)
    span = xs[i + 1] - xs[i]
    return i, (x_c - xs[i]) / span


def interp_linear(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """Interpolação linear com saturação nas bordas; ``xs`` estritamente crescente."""
    if len(xs) != len(ys) or len(xs) < 2:  # noqa: PLR2004
        raise ValueError("xs e ys precisam do mesmo comprimento (≥ 2)")
    i, f = _locate(xs, x)
    return ys[i] + f * (ys[i + 1] - ys[i])


def interp1d(grid: Grid1D, x: float) -> float:
    """Valor de ``grid`` em ``x`` (linear, saturado)."""
    return interp_linear(grid.x_values, grid.values, x)


def interp2d(grid: Grid2D, x: float, y: float) -> float:
    """Valor de ``grid`` em ``(x, y)`` (bilinear, saturado); linhas = y, colunas = x."""
    j, fx = _locate(grid.x_values, x)
    i, fy = _locate(grid.y_values, y)
    z = grid.z_values
    low = (1.0 - fx) * z[i][j] + fx * z[i][j + 1]
    high = (1.0 - fx) * z[i + 1][j] + fx * z[i + 1][j + 1]
    return (1.0 - fy) * low + fy * high
