"""Limitador de rotação com fase soft e fase hard (ecu-core RF-16, Apêndice B).

- ``f = clamp((rpm − (hard − janela)) / janela, 0, 1)`` com ``soft_enabled``;
- fase soft: retardo extra ``f · soft_retard_max_deg`` em todos os modos; em
  ``rolling_cut`` corta ainda ``floor(f · n_cyl)`` cilindros pelo padrão rotativo
  determinístico ``(contador_de_ciclo + k) mod n_cyl``;
- fase hard: com ``rpm ≥ hard`` corta todos os cilindros (``fuel_cut`` corta
  combustível; ``spark_cut`` e ``rolling_cut`` cortam faísca) até ``rpm < hard −
  histerese``; a entrada na fase hard emite ``limiter_hit``.
"""

from __future__ import annotations

from typing import Literal

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.contracts import RevLimiterConfig
from simremap.ecu.strategies.base import TickContext

__all__ = ["RevLimiter", "cut_kind"]


def cut_kind(mode: str) -> Literal["fuel_cut", "spark_cut"]:
    """Tipo de corte de um ``CutMode`` (``rolling_cut`` corta faísca)."""
    return "fuel_cut" if mode == "fuel_cut" else "spark_cut"


class RevLimiter:
    __slots__ = (
        "cut_mode",
        "enabled",
        "hard",
        "hard_active",
        "hyst",
        "kind",
        "soft_enabled",
        "soft_fraction",
        "soft_max",
        "state",
        "window",
    )

    def __init__(self, cfg: RevLimiterConfig | None) -> None:
        c = cfg if cfg is not None else RevLimiterConfig(enabled=False)
        self.enabled = c.enabled
        self.hard = c.hard_rpm
        self.cut_mode = c.cut_mode
        self.kind = cut_kind(c.cut_mode)
        self.soft_enabled = c.soft_enabled and c.soft_window_rpm > 0.0
        self.window = c.soft_window_rpm
        self.soft_max = c.soft_retard_max_deg
        self.hyst = c.hysteresis_rpm
        self.hard_active = False
        self.soft_fraction = 0.0
        self.state: Literal["off", "soft", "hard"] = "off"

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:
        if not self.enabled:
            self.state = "off"
            return
        rpm = ctx.rpm
        if self.hard_active:
            if rpm < self.hard - self.hyst:
                self.hard_active = False
        elif rpm >= self.hard:
            self.hard_active = True
            ctx.emit("limiter_hit", value=rpm, detail=self.cut_mode)
        if self.hard_active:
            self.state = "hard"
            self.soft_fraction = 1.0
            req.cut_all(self.kind)
            return
        f = 0.0
        if self.soft_enabled:
            f = (rpm - (self.hard - self.window)) / self.window
            f = 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)
        self.soft_fraction = f
        if f <= 0.0:
            self.state = "off"
            return
        self.state = "soft"
        req.active = True
        req.ign_retard = f * self.soft_max
        if self.cut_mode == "rolling_cut":
            req.cut_pattern("spark_cut", int(f * ctx.n_cyl), ctx.cycle_counter)
