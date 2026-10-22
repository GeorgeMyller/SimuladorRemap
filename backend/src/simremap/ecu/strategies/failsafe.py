"""Failsafe: regras de proteção com confirmação, ação e liberação.

Fontes: ecu-core RF-22, Apêndice E; D-BUS-04.

Condições por regra (``threshold`` na unidade da regra):

- ``egt_high``/``egt_critical``: ``egt_collector_c`` > limiar (D-BUS-04); libera abaixo
  do limiar − histerese (20 °C no ``egt_high``);
- ``lean_under_load``: ``λ_medido − λ_alvo > limiar`` com MAP ≥ 150 kPa e sonda válida;
- ``ect_high``: ECT > limiar; libera abaixo de limiar − 5 °C;
- ``oil_pressure_low``: com o motor a rodar (RPM ≥ 500), pressão de óleo abaixo de
  ``oil_pressure_min(rpm)`` (sem a tabela, abaixo de ``threshold`` se > 0);
- ``overspeed``: RPM > ``FailsafeConfig.overspeed_rpm``; libera abaixo de − 300 rpm;
- ``sensor_fault``: sensor inválido (MAP/IAT/ECT, EC-04/EC-15).

A condição tem de durar ``confirm_s`` para disparar (``failsafe_trip``); a liberação
exige a condição de saída por ``release_s`` (``failsafe_release``); com
``latch_until_stop`` só libera com RPM < 500. Ações: ``fuel_cut`` (corte total),
``boost_cut`` (duty 0 %), ``boost_reduce`` (teto = alvo − kPa, ou alvo · fração),
``rev_limit_reduce`` (corte de combustível acima da RPM, histerese 100 rpm), ``enrich``
(Δλ) e ``ignition_retard`` (graus). Valores: ver ``limits.ACTION_DEFAULTS``.
"""

from __future__ import annotations

from math import inf

from simremap.ecu.arbitration import StrategyRequest
from simremap.ecu.compiled import CompiledCalibration
from simremap.ecu.contracts import FailsafeConfig, FailsafeRule, TableKind
from simremap.ecu.limits import (
    ACTION_DEFAULTS,
    CRANK_STOP_RPM,
    FAILSAFE_RELEASE_HYSTERESIS,
    LEAN_MIN_MAP_KPA,
    PARAMETRIC_ACTIONS,
)
from simremap.ecu.strategies.base import TickContext

__all__ = ["ACTION_ORDER", "Failsafe", "RuleState"]

ACTION_ORDER: tuple[str, ...] = (
    "boost_reduce",
    "boost_cut",
    "rev_limit_reduce",
    "enrich",
    "ignition_retard",
    "fuel_cut",
)
_REV_HYST_RPM = 100.0
_EPS = 1e-9


def _action_values(rule: FailsafeRule) -> dict[str, tuple[str, float]]:
    defaults = {**ACTION_DEFAULTS["*"], **ACTION_DEFAULTS.get(rule.rule_id, {})}
    values: dict[str, tuple[str, float]] = {}
    first = True
    for action in rule.actions:
        if action not in PARAMETRIC_ACTIONS:
            continue
        kind, value = defaults[action]
        if first and rule.action_value != 0.0:
            kind = "kpa" if action == "boost_reduce" else kind
            value = rule.action_value
        first = False
        values[action] = (kind, value)
    return values


class RuleState:
    __slots__ = (
        "actions",
        "clear_since",
        "cond_since",
        "confirm_s",
        "hyst",
        "latch",
        "release_s",
        "rev_cutting",
        "rule_id",
        "threshold",
        "tripped",
        "values",
    )

    def __init__(self, rule: FailsafeRule, overspeed_rpm: float) -> None:
        self.rule_id = rule.rule_id
        self.threshold = overspeed_rpm if rule.rule_id == "overspeed" else rule.threshold
        self.confirm_s = rule.confirm_s
        self.release_s = rule.release_s
        self.latch = rule.latch_until_stop
        self.actions = tuple(rule.actions)
        self.values = _action_values(rule)
        self.hyst = FAILSAFE_RELEASE_HYSTERESIS.get(rule.rule_id, 0.0)
        self.cond_since = inf
        self.clear_since = inf
        self.tripped = False
        self.rev_cutting = False


class Failsafe:
    __slots__ = ("active_actions", "enabled", "rules", "tables")

    def __init__(self, cfg: FailsafeConfig | None, compiled: CompiledCalibration) -> None:
        self.tables = compiled
        self.enabled = cfg is not None and cfg.enabled
        self.rules: list[RuleState] = []
        if cfg is not None:
            self.rules = [RuleState(r, cfg.overspeed_rpm) for r in cfg.rules if r.enabled]
        self.active_actions: list[str] = []

    def set_compiled(self, compiled: CompiledCalibration) -> None:
        self.tables = compiled

    def _conditions(self, rule: RuleState, ctx: TickContext) -> tuple[bool, bool]:
        """(condição de disparo, condição de liberação)."""
        rid = rule.rule_id
        thr = rule.threshold
        if rid in ("egt_high", "egt_critical"):
            v = ctx.egt_c
            return v > thr, v < thr - rule.hyst
        if rid == "lean_under_load":
            cond = (
                ctx.lambda_valid
                and ctx.map_kpa >= LEAN_MIN_MAP_KPA
                and ctx.lambda_measured - ctx.lambda_target_prev > thr
            )
            return cond, not cond
        if rid == "ect_high":
            return ctx.ect_c > thr, ctx.ect_c < thr - rule.hyst
        if rid == "oil_pressure_low":
            table = self.tables.tables.get(TableKind.OIL_PRESSURE_MIN)
            minimum = table.at(ctx.inputs) if table is not None else thr
            cond = ctx.rpm >= CRANK_STOP_RPM and minimum > 0.0 and ctx.oil_pressure_kpa < minimum
            return cond, not cond
        if rid == "overspeed":
            return ctx.rpm > thr, ctx.rpm < thr - rule.hyst
        cond = ctx.sensor_fault  # sensor_fault
        return cond, not cond

    def _step_rule(self, rule: RuleState, ctx: TickContext) -> None:
        t = ctx.t
        cond, clear = self._conditions(rule, ctx)
        if not rule.tripped:
            if cond:
                if rule.cond_since == inf:
                    rule.cond_since = t
                if t - rule.cond_since >= rule.confirm_s - _EPS:
                    rule.tripped = True
                    rule.clear_since = inf
                    ctx.emit("failsafe_trip", value=rule.threshold, detail=rule.rule_id)
            else:
                rule.cond_since = inf
            return
        if rule.latch:
            release = ctx.rpm < CRANK_STOP_RPM
        else:
            if clear:
                if rule.clear_since == inf:
                    rule.clear_since = t
            else:
                rule.clear_since = inf
            release = clear and t - rule.clear_since >= rule.release_s - _EPS
        if release:
            rule.tripped = False
            rule.cond_since = inf
            rule.rev_cutting = False
            ctx.emit("failsafe_release", value=rule.threshold, detail=rule.rule_id)

    def update(self, ctx: TickContext, req: StrategyRequest) -> None:
        if not self.enabled:
            if self.active_actions:
                self.active_actions = []
            return
        active: set[str] | None = None
        for rule in self.rules:
            self._step_rule(rule, ctx)
            if not rule.tripped:
                continue
            req.active = True
            if active is None:
                active = set()
            for action in rule.actions:
                active.add(action)
                self._apply(rule, action, ctx, req)
        self.active_actions = [a for a in ACTION_ORDER if a in active] if active else []

    @staticmethod
    def _apply(rule: RuleState, action: str, ctx: TickContext, req: StrategyRequest) -> None:
        if action == "fuel_cut":
            req.cut_all("fuel_cut")
            return
        if action == "boost_cut":
            req.boost_cut = True
            return
        kind, value = rule.values[action]
        if action == "boost_reduce":
            target = ctx.boost_target_kpa
            ceiling = target * value if kind == "ratio" else target - value
            req.boost_ceiling_kpa = min(req.boost_ceiling_kpa, ceiling)
        elif action == "rev_limit_reduce":
            if rule.rev_cutting:
                rule.rev_cutting = ctx.rpm >= value - _REV_HYST_RPM
            else:
                rule.rev_cutting = ctx.rpm >= value
            if rule.rev_cutting:
                req.cut_all("fuel_cut")
        elif action == "enrich":
            delta = -abs(value)
            req.lambda_delta = min(req.lambda_delta, delta)
        else:  # ignition_retard
            retard = abs(value)
            req.ign_retard = max(req.ign_retard, retard)
