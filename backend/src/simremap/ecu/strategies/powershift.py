"""Powershift: corte na troca de marcha sem tirar o pé (ecu-core RF-19, C-07).

- Gatilho: borda de subida de ``shift_request`` (ou de ``clutch_pressed``) com TPS ≥
  ``min_tps_pct`` e RPM ≥ ``min_rpm``; uma nova borda só é aceite depois de o sinal
  voltar a ``False``;
- corte (``fuel_cut`` ou ``spark_cut``, todos os cilindros) durante exatamente
  ``round(cut_time_ms / 1000 / dt)`` ticks (120 ticks com 120 ms a 1000 Hz);
- retomada: retardo relativo ``resume_retard_deg`` em rampa linear até 0 durante
  ``resume_ramp_s``.
"""

from __future__ import annotations

from math import inf

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.contracts import PowershiftConfig
from simremap.ecu.strategies.base import TickContext

__all__ = ["Powershift"]


class Powershift:
    __slots__ = ("armed", "cfg", "resume_t", "ticks_left")

    def __init__(self, cfg: PowershiftConfig | None) -> None:
        self.cfg = cfg if cfg is not None else PowershiftConfig(enabled=False)
        self.armed = True
        self.ticks_left = 0
        self.resume_t = -inf

    @property
    def cutting(self) -> bool:
        return self.ticks_left > 0

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:
        c = self.cfg
        if not c.enabled:
            return
        signal = ctx.shift_request if c.trigger == "shift_request" else ctx.clutch_pressed
        if not signal:
            self.armed = True
        elif (
            self.armed
            and self.ticks_left == 0
            and ctx.tps_pct >= c.min_tps_pct
            and ctx.rpm >= c.min_rpm
        ):
            self.armed = False
            self.ticks_left = max(1, round(c.cut_time_ms / 1000.0 / ctx.dt))
        if self.ticks_left > 0:
            self.ticks_left -= 1
            req.cut_all(c.cut_mode)
            if self.ticks_left == 0:
                self.resume_t = ctx.t
            return
        if c.resume_ramp_s > 0.0 and c.resume_retard_deg > 0.0:
            u = (ctx.t - self.resume_t) / c.resume_ramp_s
            if 0.0 < u < 1.0:
                req.active = True
                req.ign_retard = c.resume_retard_deg * (1.0 - u)
