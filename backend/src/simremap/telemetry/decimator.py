"""Decimação dos ticks do laço em frames de UI (tel RF-05, RF-06; websocket-telemetry 2.2).

Fronteira: o tick ``k`` (contado desde o início da sessão) pertence ao frame
``frame_index(k) = floor(k · fps / sim_hz)``; o frame fecha no último tick da janela (quando o
índice de ``k + 1`` difere). Com razão não inteira (1000/60) as janelas alternam 16 e 17
ticks, sem deriva.

A ``fps`` é da sessão; um pedido novo vale a partir da próxima fronteira. Para que o
``frame_index`` continue contíguo após a troca (o salto de ``frame_index`` mede perda), a
contagem passa a ``base_index + floor((k − k0) · fps / sim_hz)``, com ``k0`` o 1.º tick
da nova taxa; sem troca de taxa vale a fórmula do contrato (``k0 = 0``).

Agregação por canal na janela: ``last`` (último tick), ``max``/``min`` (extremos ignorando
NaN), ``any`` (1 se algum tick tem a flag) e ``sum`` (soma ignorando NaN). Janela toda NaN
dá NaN (``null`` no frame).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

from simremap.telemetry.channels import AGG_CODES
from simremap.telemetry.contracts import Aggregation

__all__ = ["FPS_MAX", "FPS_MIN", "MAX_WINDOW_TICKS", "ClosedFrame", "FrameDecimator"]

FPS_MIN: Final = 30
FPS_MAX: Final = 60
MAX_WINDOW_TICKS: Final = 34  # ceil(1000 / 30)

_MAX = AGG_CODES[Aggregation.MAX]
_MIN = AGG_CODES[Aggregation.MIN]
_ANY = AGG_CODES[Aggregation.ANY]
_SUM = AGG_CODES[Aggregation.SUM]


@dataclass(frozen=True, slots=True)
class ClosedFrame:
    """Janela fechada: valores agregados na ordem do catálogo."""

    frame_index: int
    window_ticks: int
    tick: int  # último tick da janela
    t_sim_s: float  # tempo simulado do último tick
    values: np.ndarray  # float64, NaN = ausente
    fps: int


class FrameDecimator:
    """Acumula as linhas dos ticks e devolve o frame no último tick da janela."""

    __slots__ = (
        "_acc_any",
        "_acc_max",
        "_acc_min",
        "_acc_sum",
        "_any",
        "_base_index",
        "_base_tick",
        "_last",
        "_max",
        "_min",
        "_n",
        "_pending_fps",
        "_sum",
        "fps",
        "sim_hz",
    )

    def __init__(self, sim_hz: int, fps: int, aggregations: np.ndarray) -> None:
        if not 100 <= sim_hz <= 1000:  # noqa: PLR2004 - faixa do contrato
            raise ValueError(f"sim_hz fora de 100..1000: {sim_hz}")
        self.sim_hz = sim_hz
        self.fps = self.clamp_fps(fps)
        self._pending_fps: int | None = None
        self._base_tick = 0
        self._base_index = 0
        agg = np.asarray(aggregations)
        self._max = agg == _MAX
        self._min = agg == _MIN
        self._any = agg == _ANY
        self._sum = agg == _SUM
        size = len(agg)
        # Acumuladores da janela atualizados a cada tick (o fecho só combina; RNF-01).
        self._acc_max = np.full(size, np.nan)
        self._acc_min = np.full(size, np.nan)
        self._acc_sum = np.zeros(size)
        self._acc_any = np.zeros(size, dtype=bool)
        self._last = np.full(size, np.nan)
        self._n = 0

    @staticmethod
    def clamp_fps(fps: int) -> int:
        return min(max(int(fps), FPS_MIN), FPS_MAX)

    def set_fps(self, fps: int) -> None:
        """Nova taxa a partir da próxima fronteira de frame."""
        new = self.clamp_fps(fps)
        self._pending_fps = None if new == self.fps else new

    def index(self, tick: int) -> int:
        """``frame_index`` do tick com a taxa atual."""
        return self._base_index + ((tick - self._base_tick) * self.fps) // self.sim_hz

    @property
    def window_ticks(self) -> int:
        return self._n

    def push(
        self, tick: int, t_sim_s: float, row: Sequence[float] | np.ndarray
    ) -> ClosedFrame | None:
        """Acrescenta o tick; devolve o frame se este for o último tick da janela."""
        values = np.asarray(row, dtype=np.float64)
        nan = np.isnan(values)
        clean = np.where(nan, 0.0, values)
        if self._n == 0:
            self._acc_max[:] = values
            self._acc_min[:] = values
            self._acc_sum[:] = clean
            np.not_equal(clean, 0.0, out=self._acc_any)
        else:
            np.fmax(self._acc_max, values, out=self._acc_max)
            np.fmin(self._acc_min, values, out=self._acc_min)
            np.add(self._acc_sum, clean, out=self._acc_sum)
            self._acc_any |= clean != 0.0
        self._last[:] = values
        self._n += 1
        index = self.index(tick)
        if self.index(tick + 1) == index and self._n < MAX_WINDOW_TICKS:
            return None
        frame = ClosedFrame(
            frame_index=index,
            window_ticks=self._n,
            tick=tick,
            t_sim_s=t_sim_s,
            values=self._aggregate(),
            fps=self.fps,
        )
        self._n = 0
        if self._pending_fps is not None:
            self._base_index = index + 1
            self._base_tick = tick + 1
            self.fps = self._pending_fps
            self._pending_fps = None
        return frame

    def _aggregate(self) -> np.ndarray:
        out: np.ndarray = np.where(self._max, self._acc_max, self._last)
        out = np.where(self._min, self._acc_min, out)
        out = np.where(self._any, self._acc_any.astype(np.float64), out)
        return np.where(self._sum, self._acc_sum, out)
