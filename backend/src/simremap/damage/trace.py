"""Buffer circular de 30 s simulados para o laudo forense (RF-22; RNF-04).

Dois anéis NumPy pré-alocados (sem alocação por tick):

- ``tick``: uma linha a cada 10 ms simulados (100 Hz) e sempre no tick de uma falha;
- ``cycle``: uma linha por ``CombustionEvent`` (``DamageTraceRecord``).

``freeze()`` devolve um ``DamageTraceSnapshot`` imutável (cópias em ordem cronológica,
só com as linhas dentro da janela de ``trace_window_s``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
from numpy.typing import NDArray

from simremap.damage.config import DamageConfig
from simremap.damage.contracts import ComponentHealth, FailureEvent
from simremap.damage.mechanical import StructuralLimits

__all__ = [
    "CYCLE_FIELDS",
    "TICK_CYLINDER_FIELDS",
    "TICK_SCALAR_FIELDS",
    "TRACE_HZ",
    "DamageTraceSnapshot",
    "TraceBuffer",
    "TraceMeta",
]

TRACE_HZ: Final = 100.0
TICK_SCALAR_FIELDS: Final = (
    "t_sim_s",
    "tick",
    "rpm",
    "map_kpa",
    "iat_c",
    "torque_nm",
    "egt_collector_c",
    "turbo_rpm",
    "lambda_collector",
    "boost_target_kpa",
    "lambda_target",
)
TICK_CYLINDER_FIELDS: Final = (
    "knock_retard_deg",
    "lambda_cyl",
    "piston_temp_eff_c",
    "hot_spot_temp_c",
    "egt_c",
    "ignition_advance_deg",
)
CYCLE_FIELDS: Final = (
    "t_sim_s",
    "cylinder",
    "rpm",
    "map_kpa",
    "lw_integral_end",
    "theta_onset_deg_atdc",
    "intensity",
    "knock_class",
    "preignition",
    "p_max_kpa",
    "p_preignition_kpa",
    "rod_load_ratio",
    "ignition_advance_deg",
    "lambda",
    "hot_spot_temp_c",
    "knock_retard_deg",
    "t_unburned_max_k",
)
KNOCK_CLASS_CODE: Final = {"none": 0.0, "light": 1.0, "moderate": 2.0, "severe": 3.0}
PREIGNITION_CODE: Final = {"none": 0.0, "hot_spot": 1.0, "lspi": 2.0}


class _Ring:
    """Anel 2D de float64 com capacidade fixa."""

    __slots__ = ("_count", "_data", "_head")

    def __init__(self, capacity: int, width: int) -> None:
        self._data = np.full((capacity, width), np.nan, dtype=np.float64)
        self._head = 0
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def row(self) -> NDArray[np.float64]:
        """Linha seguinte para escrever (sobrescreve a mais antiga quando cheio)."""
        row: NDArray[np.float64] = self._data[self._head]
        row.fill(np.nan)
        self._head = (self._head + 1) % self._data.shape[0]
        self._count = min(self._count + 1, self._data.shape[0])
        return row

    def ordered(self) -> NDArray[np.float64]:
        """Cópia em ordem cronológica."""
        cap = self._data.shape[0]
        if self._count < cap:
            return self._data[: self._count].copy()
        return np.concatenate((self._data[self._head :], self._data[: self._head]))

    def clear(self) -> None:
        self._head = 0
        self._count = 0


@dataclass(frozen=True, slots=True)
class TraceMeta:
    session_id: str
    vehicle_id: str
    fuel_id: str
    seed: int
    sim_hz: int
    n_cyl: int
    damage_enabled: bool
    component_ids: tuple[str, ...]
    limits: StructuralLimits
    hot_spot_threshold_c: float
    stock_boost_kpa: float | None  # boost de série (maior map_target do catálogo)
    octane: float  # ON = (RON + MON)/2 do combustível
    config: DamageConfig


@dataclass(frozen=True, slots=True)
class DamageTraceSnapshot:
    """Cópia imutável do buffer (entrada pura do ``build_forensic_report``)."""

    meta: TraceMeta
    tick: Mapping[str, NDArray[np.float64]]  # escalares 1D; por cilindro 2D; "health" 2D
    cycle: Mapping[str, NDArray[np.float64]]
    components: tuple[ComponentHealth, ...]
    failures: tuple[FailureEvent, ...]
    t_start_s: float
    t_end_s: float
    extra: Mapping[str, float] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.t_end_s - self.t_start_s)

    def health_of(self, component_id: str) -> NDArray[np.float64]:
        index = self.meta.component_ids.index(component_id)
        return self.tick["health"][:, index]


class TraceBuffer:
    """Buffer circular do dano (sem alocação por tick)."""

    __slots__ = ("_cycle", "_last_bucket", "_meta", "_n_comp", "_n_cyl", "_tick", "_window_s")

    def __init__(self, meta: TraceMeta) -> None:
        self._meta = meta
        self._n_cyl = meta.n_cyl
        self._n_comp = len(meta.component_ids)
        self._window_s = meta.config.trace_window_s
        tick_rows = math.ceil(self._window_s * TRACE_HZ) + 64
        rpm_cap = max(meta.limits.valve_float_rpm * 1.2, 8000.0)
        cycle_rows = math.ceil(self._window_s * rpm_cap / 120.0 * self._n_cyl) + 64
        width = len(TICK_SCALAR_FIELDS) + self._n_cyl * len(TICK_CYLINDER_FIELDS) + self._n_comp
        self._tick = _Ring(tick_rows, width)
        self._cycle = _Ring(cycle_rows, len(CYCLE_FIELDS))
        self._last_bucket = -1

    @property
    def meta(self) -> TraceMeta:
        return self._meta

    def should_record_tick(self, t_sim_s: float) -> bool:
        """Decimação a 100 Hz por fronteira de 10 ms simulados."""
        return math.floor(t_sim_s * TRACE_HZ + 1e-9) != self._last_bucket

    def record_tick(
        self,
        scalars: Mapping[str, float | None],
        per_cylinder: Mapping[str, Sequence[float | None] | None],
        health: NDArray[np.float64],
    ) -> None:
        """Grava uma linha de tick (``None`` vira NaN)."""
        t = float(scalars["t_sim_s"] or 0.0)
        self._last_bucket = math.floor(t * TRACE_HZ + 1e-9)
        row = self._tick.row()
        for i, name in enumerate(TICK_SCALAR_FIELDS):
            value = scalars.get(name)
            if value is not None:
                row[i] = value
        base = len(TICK_SCALAR_FIELDS)
        for j, name in enumerate(TICK_CYLINDER_FIELDS):
            values = per_cylinder.get(name)
            if values is None:
                continue
            start = base + j * self._n_cyl
            for c, value in enumerate(values):
                if value is not None:
                    row[start + c] = value
        row[base + self._n_cyl * len(TICK_CYLINDER_FIELDS) :] = health

    def record_cycle(self, values: Mapping[str, float | None]) -> None:
        """Grava um ``DamageTraceRecord`` de ciclo."""
        row = self._cycle.row()
        for i, name in enumerate(CYCLE_FIELDS):
            value = values.get(name)
            if value is not None:
                row[i] = value

    def clear(self) -> None:
        self._tick.clear()
        self._cycle.clear()
        self._last_bucket = -1

    def freeze(
        self,
        components: list[ComponentHealth],
        failures: list[FailureEvent],
        t_now_s: float,
        extra: Mapping[str, float] | None = None,
    ) -> DamageTraceSnapshot:
        """Snapshot imutável com as linhas dos últimos ``trace_window_s``."""
        t_min = t_now_s - self._window_s
        ticks = self._tick.ordered()
        ticks = ticks[ticks[:, 0] >= t_min - 1e-9] if ticks.size else ticks
        cycles = self._cycle.ordered()
        cycles = cycles[cycles[:, 0] >= t_min - 1e-9] if cycles.size else cycles
        tick_cols: dict[str, NDArray[np.float64]] = {}
        for i, name in enumerate(TICK_SCALAR_FIELDS):
            tick_cols[name] = ticks[:, i].copy() if ticks.size else np.empty(0)
        base = len(TICK_SCALAR_FIELDS)
        for j, name in enumerate(TICK_CYLINDER_FIELDS):
            start = base + j * self._n_cyl
            tick_cols[name] = (
                ticks[:, start : start + self._n_cyl].copy()
                if ticks.size
                else np.empty((0, self._n_cyl))
            )
        health_start = base + self._n_cyl * len(TICK_CYLINDER_FIELDS)
        tick_cols["health"] = (
            ticks[:, health_start:].copy() if ticks.size else np.empty((0, self._n_comp))
        )
        cycle_cols = {
            name: (cycles[:, i].copy() if cycles.size else np.empty(0))
            for i, name in enumerate(CYCLE_FIELDS)
        }
        for array in (*tick_cols.values(), *cycle_cols.values()):
            array.flags.writeable = False
        t_start = float(tick_cols["t_sim_s"][0]) if tick_cols["t_sim_s"].size else t_now_s
        return DamageTraceSnapshot(
            meta=self._meta,
            tick=tick_cols,
            cycle=cycle_cols,
            components=tuple(components),
            failures=tuple(failures),
            t_start_s=t_start,
            t_end_s=t_now_s,
            extra=dict(extra or {}),
        )
