"""Overrun: DFCO e pops & bangs com proteção de turbina e catalisador (ecu-core RF-20, RF-21).

Máquina de estados por evento de desaceleração (pedal fechado):

- ``pops``: com ``pops_enabled``, RPM em ``[pops_rpm_min, pops_rpm_max]`` e TPS ≤
  ``pops_tps_max_pct``, desde a liberação do pedal até a janela ``min(fuel_cut_delay_s,
  duração)``: ignição absoluta ``ign_advance_deg`` e lambda ``lambda_target``. A
  intensidade efetiva é a fração de cilindros, por ciclo, que recebem combustível
  (padrão rotativo); os outros ficam em corte. Duração ``max_duration_s``;
- após a janela de pops há corte de injeção (``cut``) até a RPM cair abaixo de
  ``dfco_resume_rpm`` ou o pedal abrir;
- ``DFCO`` normal (fora da janela de pops, pops desligado ou protegido): TPS ≤
  ``dfco_tps_max_pct`` e RPM ≥ ``dfco_rpm_min`` durante ``dfco_delay_s`` ⇒ corte até
  ``rpm < dfco_resume_rpm`` ou pedal aberto;
- proteção: EGT do coletor (pré-turbina, D-BUS-04) ≥ ``egt_turbine_max_c`` suspende o
  pops no mesmo tick e emite ``overrun_protect``; com ``catalyst_present`` a intensidade
  fica ≤ ``catalyst_max_intensity_pct`` e a duração ≤ ``catalyst_max_duration_s``.
"""

from __future__ import annotations

from math import inf
from typing import Literal

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.contracts import OverrunConfig
from simremap.ecu.strategies.base import TickContext

__all__ = ["Overrun"]

OverrunState = Literal["idle", "pops", "cut"]


class Overrun:
    __slots__ = (
        "cfg",
        "closed_since",
        "effective_duration_s",
        "effective_intensity_pct",
        "protected",
        "state",
        "window_s",
    )

    def __init__(self, cfg: OverrunConfig | None) -> None:
        c = cfg if cfg is not None else OverrunConfig(enabled=False)
        self.cfg = c
        intensity = c.intensity_pct
        duration = c.max_duration_s
        if c.catalyst_present:
            intensity = min(intensity, c.catalyst_max_intensity_pct)
            duration = min(duration, c.catalyst_max_duration_s)
        self.effective_intensity_pct = intensity
        self.effective_duration_s = duration
        self.window_s = min(c.fuel_cut_delay_s, duration)
        self.state: OverrunState = "idle"
        self.closed_since = inf
        self.protected = False

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:
        c = self.cfg
        if not c.enabled:
            self.state = "idle"
            return
        t = ctx.t
        rpm = ctx.rpm
        tps = ctx.tps_pct
        closed_max = max(c.pops_tps_max_pct if c.pops_enabled else 0.0, c.dfco_tps_max_pct)
        if tps > closed_max:
            self.state = "idle"
            self.closed_since = inf
            self.protected = False
            return
        if self.closed_since == inf:
            self.closed_since = t
        elapsed = t - self.closed_since
        pops_ok = (
            c.pops_enabled
            and not self.protected
            and tps <= c.pops_tps_max_pct
            and c.pops_rpm_min <= rpm <= c.pops_rpm_max
        )
        if pops_ok and ctx.egt_c >= c.egt_turbine_max_c:
            self.protected = True
            pops_ok = False
            ctx.emit("overrun_protect", value=ctx.egt_c, detail="egt_turbine")
        if self.state == "cut":
            if rpm < c.dfco_resume_rpm:
                self.state = "idle"
        elif pops_ok and elapsed < self.window_s:
            self.state = "pops"
        elif self.state == "pops" and pops_ok and rpm >= c.dfco_resume_rpm:
            self.state = "cut"  # fim da janela: corte de injeção atrasado
        else:
            self.state = "idle"
            if (
                c.dfco_enabled
                and tps <= c.dfco_tps_max_pct
                and rpm >= c.dfco_rpm_min
                and elapsed >= c.dfco_delay_s - 1e-9
            ):
                self.state = "cut"
        if self.state == "cut":
            req.cut_all("fuel_cut")
        elif self.state == "pops":
            req.active = True
            req.ign_override = c.ign_advance_deg
            req.lambda_target = c.lambda_target
            n = ctx.n_cyl
            firing = round(self.effective_intensity_pct / 100.0 * n)
            req.cut_pattern("fuel_cut", n - firing, ctx.cycle_counter)
