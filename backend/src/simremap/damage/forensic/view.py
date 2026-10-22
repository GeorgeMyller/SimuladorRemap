"""Leitura do ``DamageTraceSnapshot`` limitada ao instante da falha (sem I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from simremap.damage.trace import DamageTraceSnapshot

__all__ = ["MAX_RETARD_DEG", "Crossing", "TraceView"]

MAX_RETARD_DEG: Final = 8.0  # padrão max_retard_deg do ecu-core (C.2)
_EPS: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Crossing:
    t_sim_s: float
    value: float
    cylinder: int | None = None


class TraceView:
    """Colunas do buffer até ``t_f`` (inclusive)."""

    def __init__(self, trace: DamageTraceSnapshot, t_failure_s: float) -> None:
        self.trace = trace
        self.t_f = t_failure_s
        tick_t = trace.tick["t_sim_s"]
        cycle_t = trace.cycle["t_sim_s"]
        self._tick_mask = tick_t <= t_failure_s + _EPS
        self._cycle_mask = cycle_t <= t_failure_s + _EPS

    def tick(self, name: str) -> NDArray[np.float64]:
        return self.trace.tick[name][self._tick_mask]

    def cycle(self, name: str) -> NDArray[np.float64]:
        return self.trace.cycle[name][self._cycle_mask]

    @property
    def t(self) -> NDArray[np.float64]:
        return self.tick("t_sim_s")

    @property
    def t_start(self) -> float:
        t = self.t
        return float(t[0]) if t.size else self.t_f

    def first_true(self, mask: NDArray[np.bool_], values: NDArray[np.float64]) -> Crossing | None:
        """Primeira amostra de tick com ``mask`` verdadeiro."""
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return None
        k = int(idx[0])
        return Crossing(float(self.t[k]), float(values[k]))

    def first_sustained(
        self, mask: NDArray[np.bool_], values: NDArray[np.float64], duration_s: float
    ) -> Crossing | None:
        """Primeiro instante em que ``mask`` fica verdadeiro durante ``duration_s``."""
        t = self.t
        start: float | None = None
        for k in range(t.size):
            if bool(mask[k]):
                if start is None:
                    start = float(t[k])
                if float(t[k]) - start >= duration_s - _EPS:
                    return Crossing(float(t[k]), float(values[k]))
            else:
                start = None
        return None

    def first_cylinder_crossing(
        self, name: str, threshold: float, *, greater_equal: bool = True
    ) -> Crossing | None:
        """Primeira amostra em que algum cilindro de ``name`` atinge ``threshold``."""
        data = self.tick(name)
        if data.size == 0:
            return None
        mask = data >= threshold if greater_equal else data <= threshold
        rows = np.flatnonzero(mask.any(axis=1))
        if rows.size == 0:
            return None
        k = int(rows[0])
        cyl = int(np.flatnonzero(mask[k])[0])
        return Crossing(float(self.t[k]), float(data[k, cyl]), cyl + 1)

    def lambda_series(self) -> NDArray[np.float64]:
        """λ do coletor (ou média dos cilindros quando ausente)."""
        collector = self.tick("lambda_collector")
        per_cyl = self.tick("lambda_cyl")
        if per_cyl.size == 0:
            return collector
        valid = ~np.isnan(per_cyl)
        counts = valid.sum(axis=1)
        sums = np.where(valid, per_cyl, 0.0).sum(axis=1)
        mean = np.divide(sums, counts, out=np.full(sums.shape, np.nan), where=counts > 0)
        return np.where(np.isnan(collector), mean, collector)

    def first_cycle(self, mask: NDArray[np.bool_]) -> int | None:
        idx = np.flatnonzero(mask)
        return int(idx[0]) if idx.size else None
