"""``EvaluationTrace`` a 100 Hz a partir do ``DataLog`` (training-scenarios RF-11, seção 8).

Agregação fixa por janela de 10 ms de ``t_sim_s`` (janela ``w = floor(tick · 100 / sim_hz)``
relativa ao tick da sessão, ``t_sim_s`` da linha = ``w / 100``):

| coluna | origem no DataLog | agregação | casas |
|---|---|---|---|
| ``rpm`` | ``rpm`` | média | 1 |
| ``pedal_pct`` | ``pedal_pct`` (pedal da bancada; ver abaixo) | média | 1 |
| ``egt_collector_c`` | ``egt_pre_turbo_c`` (``SensorReadings.egt_collector_c``) | máx. | 1 |
| ``lambda_min`` / ``lambda_max`` | ``lambda_measured`` | mín. / máx. | 4 |
| ``knock_retard_max_deg`` | ``knock_retard_deg`` (máx. dos cilindros) | máx. | 2 |
| ``pop_events`` | ``overrun_afterfire`` | soma | 0 |
| ``overrun_active`` | fase ``coastdown`` da puxada | OU lógico | — |
| ``health_min_pct`` | ``health_min_pct`` | mín. | 3 |
| ``phase`` | ``run.state`` do log (``arming``, ``running``, ``coastdown``) | última | — |

Decisões de interpretação (registadas no relatório): o pedal é o canal ``pedal_pct`` do
DataLog (``DynoLoad.pedal_pct``, com a rampa de 100 %/s e o limitador do arming). Logs
antigos ou importados sem esse canal usam o pedal do ``DynoRunRequest`` pela fase (o dyno usa
o pedal do pedido em ``arming`` e ``running`` e 0 no ``coastdown``). ``overrun_active`` =
fase ``coastdown`` (motor arrastado pelo rolo com o pedal a 0); o ``cooldown`` do
``multi_pull`` conta como ``coastdown`` sem overrun. Valores não finitos viram ``None``.

O traço só depende do log (colunas ``float32``) e do pedido: o mesmo log gera sempre as
mesmas linhas, na estação do aluno e na do instrutor.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Final, Literal

import numpy as np
from pydantic import Field, model_validator

from simremap.core.contracts import ContractModel
from simremap.telemetry.datalog import LogData

__all__ = [
    "TRACE_COLUMNS",
    "TRACE_HZ",
    "EvaluationTrace",
    "TraceRow",
    "build_trace",
    "phase_of",
    "q",
]

TRACE_HZ: Final = 100
TRACE_COLUMNS: Final[tuple[str, ...]] = (
    "t_sim_s",
    "rpm",
    "pedal_pct",
    "egt_collector_c",
    "lambda_min",
    "lambda_max",
    "knock_retard_max_deg",
    "pop_events",
    "overrun_active",
    "health_min_pct",
    "phase",
)
MAX_ROWS: Final = 60_000  # 600 s a 100 Hz (puxadas truncadas a 300 s + multi_pull)

Phase = Literal["arming", "running", "coastdown"]
TraceRow = list[Any]

_CHANNELS: Final[dict[str, str]] = {
    "rpm": "rpm",
    "egt": "egt_pre_turbo_c",
    "lambda": "lambda_measured",
    "knock": "knock_retard_deg",
    "pops": "overrun_afterfire",
    "health": "health_min_pct",
}
_PHASES: Final[dict[str, Phase]] = {
    "arming": "arming",
    "pull": "running",
    "cells": "running",
    "running": "running",
    "coastdown": "coastdown",
    "cooldown": "coastdown",
}


def q(value: float | None, places: int) -> float | None:
    """Arredondamento ``ROUND_HALF_EVEN`` via ``Decimal`` (``None`` para não finitos)."""
    if value is None or not math.isfinite(value):
        return None
    exp = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(exp, rounding=ROUND_HALF_EVEN))


class EvaluationTrace(ContractModel):
    """Traço de avaliação de uma puxada (ou de 1 puxada de um ``multi_pull``)."""

    run_id: str = Field(min_length=1, max_length=36)
    pull_index: int = Field(0, ge=0)  # 0 = puxada única
    columns: tuple[str, ...] = TRACE_COLUMNS
    rows: list[TraceRow] = Field(default_factory=list, max_length=MAX_ROWS)

    @model_validator(mode="after")
    def _check(self) -> EvaluationTrace:
        if tuple(self.columns) != TRACE_COLUMNS:
            raise ValueError("EvaluationTrace.columns fora da ordem fixa")
        width = len(TRACE_COLUMNS)
        if any(len(r) != width for r in self.rows):
            raise ValueError(f"EvaluationTrace: cada linha deve ter {width} colunas")
        return self

    def column(self, name: str) -> list[Any]:
        i = TRACE_COLUMNS.index(name)
        return [r[i] for r in self.rows]

    @property
    def empty(self) -> bool:
        return not self.rows


def phase_of(log: LogData) -> list[Phase]:
    """Fase de cada amostra pelos eventos ``run.state`` do cabeçalho do log."""
    n = log.header.n_samples
    marks: list[tuple[int, Phase]] = []
    for event in log.header.events:
        if event.type != "run.state":
            continue
        payload = event.payload
        raw = payload.get("phase") or payload.get("state")
        phase = _PHASES.get(str(raw))
        if phase is None:
            continue
        marks.append((event.index, phase))
    marks.sort(key=lambda m: m[0])
    phases: list[Phase] = ["arming"] * n
    current: Phase = "arming"
    j = 0
    for i in range(n):
        while j < len(marks) and marks[j][0] <= i:
            current = marks[j][1]
            j += 1
        phases[i] = current
    return phases


def _raw_phase(log: LogData) -> list[str]:
    n = log.header.n_samples
    marks = sorted(
        (e.index, str(e.payload.get("phase") or e.payload.get("state")))
        for e in log.header.events
        if e.type == "run.state"
    )
    out = ["arming"] * n
    current = "arming"
    j = 0
    for i in range(n):
        while j < len(marks) and marks[j][0] <= i:
            current = marks[j][1]
            j += 1
        out[i] = current
    return out


def _col(log: LogData, name: str) -> np.ndarray:
    if log.has(name):
        return np.asarray(log.column(name), dtype=np.float64)
    return np.full(log.header.n_samples, np.nan)


def _agg(values: np.ndarray, how: str) -> float | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    if how == "mean":
        return float(np.mean(finite))
    if how == "max":
        return float(np.max(finite))
    if how == "min":
        return float(np.min(finite))
    return float(np.sum(finite))


def build_trace(
    log: LogData,
    *,
    run_id: str,
    pedal_pct: float,
    pull_index: int = 0,
    segment: tuple[int, int] | None = None,
) -> EvaluationTrace:
    """Agrega o log (ou o segmento ``[start, end)`` de uma puxada) em janelas de 10 ms."""
    header = log.header
    n = header.n_samples
    start, end = (0, n) if segment is None else (max(0, segment[0]), min(n, segment[1]))
    if end <= start:
        return EvaluationTrace(run_id=run_id, pull_index=pull_index, rows=[])
    sim_hz = header.sim_hz
    ticks = header.start_tick + np.arange(start, end, dtype=np.int64)
    windows = (ticks * TRACE_HZ) // sim_hz
    phases = phase_of(log)[start:end]
    raw = _raw_phase(log)[start:end]
    cols = {key: _col(log, name)[start:end] for key, name in _CHANNELS.items()}
    if log.has("pedal_pct"):
        pedal = _col(log, "pedal_pct")[start:end]
    else:
        pedal = np.array(
            [pedal_pct if p in ("arming", "running") else 0.0 for p in phases], dtype=np.float64
        )
    overrun = np.array([r == "coastdown" for r in raw], dtype=bool)
    rows: list[TraceRow] = []
    bounds = np.flatnonzero(np.diff(windows)) + 1
    edges: Sequence[int] = [0, *bounds.tolist(), len(windows)]
    for a, b in itertools.pairwise(edges):
        w = int(windows[a])
        pops = _agg(cols["pops"][a:b], "sum")
        rows.append(
            [
                q(w / TRACE_HZ, 2),
                q(_agg(cols["rpm"][a:b], "mean"), 1),
                q(_agg(pedal[a:b], "mean"), 1),
                q(_agg(cols["egt"][a:b], "max"), 1),
                q(_agg(cols["lambda"][a:b], "min"), 4),
                q(_agg(cols["lambda"][a:b], "max"), 4),
                q(_agg(cols["knock"][a:b], "max"), 2),
                0 if pops is None else round(pops),
                bool(np.any(overrun[a:b])),
                q(_agg(cols["health"][a:b], "min"), 3),
                phases[b - 1],
            ]
        )
    return EvaluationTrace(run_id=run_id, pull_index=pull_index, rows=rows)


def traces_for_run(
    log: LogData, *, run_id: str, pedal_pct: float, multi: bool
) -> dict[int, EvaluationTrace]:
    """Traços da puxada: ``{0: traço}`` ou, em ``multi_pull``, ``{pull_index: traço}``."""
    if not multi:
        return {0: build_trace(log, run_id=run_id, pedal_pct=pedal_pct)}
    out: dict[int, EvaluationTrace] = {}
    for seg in log.header.pulls:
        out[seg.pull_index] = build_trace(
            log,
            run_id=run_id,
            pedal_pct=pedal_pct,
            pull_index=seg.pull_index,
            segment=(seg.start_index, seg.end_index),
        )
    return out
