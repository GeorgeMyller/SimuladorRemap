"""Controle de boost: alvo 3D, teto por marcha, duty base + PID e overboost (ecu-core RF-14, RF-15).

- Alvo: ``boost_target(rpm, tps)``; com ``by_gear_enabled``, ``min(alvo,
  boost_target_gear(gear))``; depois o teto do knock. Os tetos do failsafe entram na
  arbitragem (passo 8), antes do cálculo do duty.
- Duty: ``duty_base(rpm, alvo) + kp·e + I + D`` com ``e = alvo − MAP``; ``D`` sobre a
  medida filtrada (``τ = d_filter_tau_s``); ``I`` limitado a ``±integrator_limit_pct``
  e só integra com ``MAP ≥ alvo − pid_activation_window_kpa`` (fora da janela vale só o
  duty base); duty final em 0..100 %. Convenção OQ-04: 0 % = wastegate livre (mola),
  100 % = wastegate fechada.
- Overboost: ``MAP > overboost_kpa`` por ≥ ``overboost_time_s`` ativa o corte
  (``wastegate_open``, ``fuel_cut`` ou ``spark_cut``) e emite ``overboost_cut``; rearma
  com ``MAP < overboost_kpa − overboost_hysteresis_kpa``. O pedido entra no nível
  failsafe (decisão da spec, C-06).
"""

from __future__ import annotations

from math import inf

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.compiled import QUANTITY_INDEX, CompiledCalibration
from simremap.ecu.contracts import AxisQuantity, BoostControlConfig, TableKind
from simremap.ecu.strategies.base import TickContext

__all__ = ["BoostControl"]

_K = TableKind
_BOOST_Q = QUANTITY_INDEX[AxisQuantity.BOOST_TARGET_KPA]


class BoostControl:
    __slots__ = (
        "by_gear",
        "cut_mode",
        "d_tau",
        "duty",
        "enabled",
        "integ",
        "integ_limit",
        "kd",
        "ki",
        "kp",
        "map_filt",
        "map_filt_prev",
        "mode",
        "over_since",
        "overboost_active",
        "overboost_hyst",
        "overboost_kpa",
        "overboost_time",
        "pid_active",
        "tables",
        "target_kpa",
        "window",
    )

    def __init__(self, cfg: BoostControlConfig | None, compiled: CompiledCalibration) -> None:
        self.tables = compiled
        self.integ = 0.0
        self.map_filt = -1.0
        self.map_filt_prev = -1.0
        self.over_since = inf
        self.overboost_active = False
        self.duty = 0.0
        self.target_kpa = 0.0
        self.pid_active = False
        self.configure(cfg)

    def configure(self, cfg: BoostControlConfig | None) -> None:
        c = cfg if cfg is not None else BoostControlConfig(enabled=False)
        self.enabled = c.enabled
        self.mode = c.mode
        self.kp = c.kp_pct_per_kpa
        self.ki = c.ki_pct_per_kpa_s
        self.kd = c.kd_pct_s_per_kpa
        self.d_tau = c.d_filter_tau_s
        self.window = c.pid_activation_window_kpa
        self.integ_limit = c.integrator_limit_pct
        self.by_gear = c.by_gear_enabled
        self.overboost_kpa = c.overboost_kpa
        self.overboost_time = c.overboost_time_s
        self.overboost_hyst = c.overboost_hysteresis_kpa
        self.cut_mode = c.overboost_cut_mode

    def set_compiled(self, compiled: CompiledCalibration) -> None:
        self.tables = compiled

    def target(self, ctx: TickContext, knock_reduction_kpa: float) -> float:
        """Passo 6: alvo de boost antes dos tetos do failsafe (kPa abs)."""
        tables = self.tables.tables
        inputs = ctx.inputs
        table = tables.get(_K.BOOST_TARGET)
        target = table.at(inputs) if table is not None else ctx.baro_kpa
        if self.by_gear:
            gear_t = tables.get(_K.BOOST_TARGET_GEAR)
            if gear_t is not None:
                ceiling = gear_t.at(inputs)
                target = min(target, ceiling)
        if knock_reduction_kpa > 0.0:
            target -= knock_reduction_kpa
        target = max(target, 0.0)
        ctx.boost_target_kpa = target
        return target

    def check_overboost(self, ctx: TickContext, req: StrategyRequest) -> None:
        """Avalia o overboost e escreve o pedido no ``req`` do failsafe."""
        if not self.enabled:
            self.overboost_active = False
            return
        map_kpa = ctx.map_kpa
        if self.overboost_active:
            if map_kpa < self.overboost_kpa - self.overboost_hyst:
                self.overboost_active = False
                self.over_since = inf
        elif map_kpa > self.overboost_kpa:
            if self.over_since == inf:
                self.over_since = ctx.t
            if ctx.t - self.over_since >= self.overboost_time - 1e-9:
                self.overboost_active = True
                ctx.emit("overboost_cut", value=map_kpa, detail=self.cut_mode)
        else:
            self.over_since = inf
        if self.overboost_active:
            req.active = True
            if self.cut_mode == "wastegate_open":
                req.boost_cut = True
            else:
                req.cut_all(self.cut_mode)

    def compute_duty(self, ctx: TickContext, target: float, boost_cut: bool) -> float:
        """Passo 8: duty da wastegate com o alvo final."""
        inputs = ctx.inputs
        inputs[_BOOST_Q] = target
        self.target_kpa = target
        map_kpa = ctx.map_kpa
        dt = ctx.dt
        if self.map_filt < 0.0:
            self.map_filt = map_kpa
            self.map_filt_prev = map_kpa
        self.map_filt_prev = self.map_filt
        self.map_filt += (map_kpa - self.map_filt) * dt / (self.d_tau + dt)
        if not self.enabled or boost_cut:
            self.pid_active = False
            self.duty = 0.0
            return 0.0
        base_t = self.tables.tables.get(_K.BOOST_DUTY_BASE)
        duty = base_t.at(inputs) if base_t is not None else 0.0
        self.pid_active = False
        if self.mode == "closed_loop" and map_kpa >= target - self.window:
            self.pid_active = True
            e = target - map_kpa
            integ = self.integ + self.ki * e * dt
            lim = self.integ_limit
            self.integ = lim if integ > lim else (-lim if integ < -lim else integ)
            d = -self.kd * (self.map_filt - self.map_filt_prev) / dt
            duty += self.kp * e + self.integ + d
        self.duty = 0.0 if duty < 0.0 else (100.0 if duty > 100.0 else duty)  # noqa: PLR2004
        return self.duty
