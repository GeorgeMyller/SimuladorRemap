"""Antilag com atraso de ignição, enriquecimento, abertura de ar e proteções (ecu-core RF-18, C-04).

- Ativação: ``switch`` (``antilag_switch``) ou ``rolling``; nos dois casos exige RPM em
  ``[rpm_min, rpm_max]`` e TPS ≤ ``max_tps_pct`` (antilag atua com o pedal fechado);
- ativo: ignição absoluta ``ign_advance_deg``, lambda ``lambda_target``, comando
  ``antilag_air_pct = air_valve_pct`` e corte parcial ``cut_fraction`` dos cilindros
  pelo padrão rotativo (``rolling_cut``/``spark_cut`` cortam faísca, ``fuel_cut``
  combustível);
- proteções: EGT do coletor ≥ ``egt_max_c`` ou tempo contínuo ≥ ``max_active_s``
  desligam no mesmo tick, emitem ``antilag_protect`` e só rearmam após ``cooldown_s``.
"""

from __future__ import annotations

from math import inf

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.contracts import AntilagConfig
from simremap.ecu.strategies.base import TickContext
from simremap.ecu.strategies.rev_limiter import cut_kind

__all__ = ["Antilag"]


class Antilag:
    __slots__ = ("active", "active_since", "cfg", "cooldown_until", "kind")

    def __init__(self, cfg: AntilagConfig | None) -> None:
        self.cfg = cfg if cfg is not None else AntilagConfig(enabled=False)
        self.kind = cut_kind(self.cfg.cut_mode)
        self.active = False
        self.active_since = inf
        self.cooldown_until = -inf

    def _condition(self, ctx: TickContext) -> bool:
        c = self.cfg
        if c.activation == "switch" and not ctx.antilag_switch:
            return False
        return c.rpm_min <= ctx.rpm <= c.rpm_max and ctx.tps_pct <= c.max_tps_pct

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:
        c = self.cfg
        if not c.enabled:
            return
        t = ctx.t
        cond = self._condition(ctx) and t >= self.cooldown_until
        if self.active:
            reason = ""
            if ctx.egt_c >= c.egt_max_c:
                reason = "egt"
            elif t - self.active_since >= c.max_active_s - 1e-9:
                reason = "tempo"
            if reason:
                self.active = False
                self.cooldown_until = t + c.cooldown_s
                ctx.emit("antilag_protect", value=ctx.egt_c, detail=reason)
                return
            if not cond:
                self.active = False
        elif cond and ctx.egt_c < c.egt_max_c:
            self.active = True
            self.active_since = t
        if not self.active:
            return
        req.active = True
        req.ign_override = c.ign_advance_deg
        req.lambda_target = c.lambda_target
        req.antilag_air_pct = c.air_valve_pct
        req.cut_pattern(self.kind, round(c.cut_fraction * ctx.n_cyl), ctx.cycle_counter)
