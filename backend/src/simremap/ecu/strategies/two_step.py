"""Two-step / launch control (ecu-core RF-17).

- Ativação: embraiagem (``clutch``) ou botão (``launch_switch``), com TPS ≥
  ``min_tps_pct`` e velocidade ≤ ``max_speed_kmh``;
- ativo: ignição absoluta ``ign_advance_deg``, lambda ``lambda_target`` e limite em
  ``target_rpm``: ``fuel_cut``/``spark_cut`` cortam todos os cilindros com ``rpm ≥ alvo``
  e liberam abaixo de ``alvo − 50``; ``rolling_cut`` corta uma fração proporcional ao
  excesso, ``clamp((rpm − alvo + 50) / 100, 0, 1)``, pelo padrão rotativo;
- ``max_active_s`` contínuo desativa a estratégia e emite ``two_step_timeout``; só
  rearma depois de a condição de ativação cair;
- ao sair, o retardo face ao avanço normal desaparece em rampa de ``release_ramp_s``.
"""

from __future__ import annotations

from math import inf

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.contracts import TwoStepConfig
from simremap.ecu.strategies.base import TickContext
from simremap.ecu.strategies.rev_limiter import cut_kind

__all__ = ["TwoStep"]

_BAND_RPM = 50.0


class TwoStep:
    __slots__ = (
        "active",
        "active_since",
        "cfg",
        "cutting",
        "kind",
        "locked_out",
        "ramp_from",
        "released_t",
    )

    def __init__(self, cfg: TwoStepConfig | None) -> None:
        self.cfg = cfg if cfg is not None else TwoStepConfig(enabled=False)
        self.kind = cut_kind(self.cfg.cut_mode)
        self.active = False
        self.active_since = inf
        self.locked_out = False
        self.cutting = False
        self.released_t = -inf
        self.ramp_from = 0.0

    def _condition(self, ctx: TickContext) -> bool:
        c = self.cfg
        trigger = ctx.clutch_pressed if c.activation == "clutch" else ctx.launch_switch
        return trigger and ctx.tps_pct >= c.min_tps_pct and ctx.vehicle_speed_kmh <= c.max_speed_kmh

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:  # noqa: PLR0912
        c = self.cfg
        if not c.enabled:
            return
        cond = self._condition(ctx)
        if not cond:
            self.locked_out = False
        if self.active and (not cond or ctx.t - self.active_since >= c.max_active_s - 1e-9):
            if cond:
                self.locked_out = True
                ctx.emit("two_step_timeout", value=ctx.t - self.active_since)
            self.active = False
            self.cutting = False
            self.released_t = ctx.t
            self.ramp_from = max(0.0, ctx.adv_ref - c.ign_advance_deg)
        elif not self.active and cond and not self.locked_out:
            self.active = True
            self.active_since = ctx.t
        if self.active:
            req.active = True
            req.ign_override = c.ign_advance_deg
            req.lambda_target = c.lambda_target
            rpm = ctx.rpm
            if c.cut_mode == "rolling_cut":
                f = (rpm - c.target_rpm + _BAND_RPM) / (2.0 * _BAND_RPM)
                f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
                req.cut_pattern("spark_cut", round(f * ctx.n_cyl), ctx.cycle_counter)
            else:
                if self.cutting:
                    self.cutting = rpm >= c.target_rpm - _BAND_RPM
                else:
                    self.cutting = rpm >= c.target_rpm
                if self.cutting:
                    req.cut_all(self.kind)
            return
        if c.release_ramp_s > 0.0 and self.ramp_from > 0.0:
            u = (ctx.t - self.released_t) / c.release_ramp_s
            if u < 1.0:
                req.active = True
                req.ign_retard = self.ramp_from * (1.0 - u)
