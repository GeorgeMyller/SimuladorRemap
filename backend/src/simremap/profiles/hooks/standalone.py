"""Base comum dos perfis standalone ``ft-pro``, ``m1-race`` e ``ht-elite`` (RF-14 a RF-16, RF-27).

- ``StandaloneHooks``: hooks do ecu-core com a matriz de suporte do descritor (sem modelo
  de ar próprio: o combustível vem de VE ou de ms pelo speed-density do core).
- ``protection_strategies``: converte os limites da ``BaseSetup`` em estratégias do
  ecu-core (RF-27): ``failsafe`` (regras padrão do Apêndice E do ecu-core com os
  limiares da base), ``rev_limiter.hard_rpm`` e ``boost_control.overboost_kpa``;
  ``closed_loop.enabled`` só com wideband declarada (EC-11).
- ``InjectorModel``: modelo físico do bico do ``m1-race`` (RF-15): vazão em função da
  pressão diferencial (fator sobre ``flow_cc_min``) e adição de pulso curto, aplicados ao
  pulso que a ECU comanda (o ``EcuStatus`` guarda o pulso do runtime genérico).
"""

from __future__ import annotations

from math import isfinite, sqrt
from typing import Any

from simremap.ecu.contracts import (
    BoostControlConfig,
    ClosedLoopConfig,
    FailsafeConfig,
    FailsafeRule,
    RevLimiterConfig,
    StrategyConfig,
)
from simremap.ecu.limits import default_failsafe_rules
from simremap.ecu.tables import interp1
from simremap.profiles.contracts import InjectorSetup, ProtectionLimits
from simremap.profiles.hooks.common import DescriptorHooks

__all__ = ["InjectorModel", "StandaloneHooks", "failsafe_rules", "protection_strategies"]


class StandaloneHooks(DescriptorHooks):
    """Hooks dos perfis standalone (validação pela matriz de suporte do descritor)."""


def failsafe_rules(limits: ProtectionLimits) -> list[FailsafeRule]:
    """Regras padrão com os limiares da ``BaseSetup`` (EGT, ECT, óleo, mistura, sobrerrotação)."""
    thresholds = {
        "egt_high": limits.egt_max_c,
        "ect_high": limits.ect_max_c,
        "oil_pressure_low": limits.oil_pressure_min_kpa,
        "lean_under_load": limits.lean_delta_lambda,
        "overspeed": limits.overspeed_rpm,
    }
    rules = []
    for rule in default_failsafe_rules(limits.egt_max_c, limits.overspeed_rpm):
        value = thresholds.get(rule.rule_id)
        rules.append(rule if value is None else rule.model_copy(update={"threshold": value}))
    return rules


def protection_strategies(
    limits: ProtectionLimits,
    *,
    wideband: bool,
    existing: dict[str, StrategyConfig] | None = None,
) -> dict[str, StrategyConfig]:
    """Estratégias de proteção geradas a partir da base (RF-27).

    ``existing`` preserva as outras opções já configuradas pelo usuário (ganhos do PID,
    modo de corte, etc.); só os campos derivados da base são substituídos.
    """
    old = existing or {}
    out: dict[str, StrategyConfig] = {}
    fs_old = old.get("failsafe")
    fs_data: dict[str, Any] = fs_old.model_dump() if isinstance(fs_old, FailsafeConfig) else {}
    fs_data.update(
        kind="failsafe",
        rules=[r.model_dump() for r in failsafe_rules(limits)],
        overspeed_rpm=limits.overspeed_rpm,
    )
    out["failsafe"] = FailsafeConfig.model_validate(fs_data)
    rl_old = old.get("rev_limiter")
    rl_data: dict[str, Any] = rl_old.model_dump() if isinstance(rl_old, RevLimiterConfig) else {}
    rl_data.update(kind="rev_limiter", hard_rpm=limits.rev_limit_rpm)
    if rl_data.get("soft_window_rpm", 200.0) >= limits.rev_limit_rpm:
        rl_data["soft_window_rpm"] = 200.0
    out["rev_limiter"] = RevLimiterConfig.model_validate(rl_data)
    bc_old = old.get("boost_control")
    bc_data: dict[str, Any] = bc_old.model_dump() if isinstance(bc_old, BoostControlConfig) else {}
    bc_data.update(kind="boost_control", overboost_kpa=limits.overboost_kpa)
    out["boost_control"] = BoostControlConfig.model_validate(bc_data)
    cl_old = old.get("closed_loop")
    cl_data: dict[str, Any] = cl_old.model_dump() if isinstance(cl_old, ClosedLoopConfig) else {}
    cl_data.update(kind="closed_loop", enabled=wideband)
    out["closed_loop"] = ClosedLoopConfig.model_validate(cl_data)
    return out


class InjectorModel:
    """Modelo físico do bico do ``m1-race``: fator de vazão vs ΔP e adição de pulso curto."""

    __slots__ = ("adder_ms", "adder_x", "dp_factor", "dp_x", "ref_kpa")

    def __init__(self, injectors: InjectorSetup) -> None:
        self.ref_kpa = injectors.ref_pressure_kpa
        self.dp_x = list(injectors.flow_vs_dp_kpa or [])
        self.dp_factor = list(injectors.flow_vs_dp_factor or [])
        self.adder_x = list(injectors.short_pulse_ms or [])
        self.adder_ms = list(injectors.short_pulse_adder_ms or [])

    @property
    def active(self) -> bool:
        return bool(self.dp_x or self.adder_x)

    def adjust(self, pw_ms: float, dead_ms: float, dp_kpa: float) -> float:
        """Pulso corrigido: a parte útil passa de ``sqrt(ΔP/ΔP_ref)`` ao fator tabelado."""
        if pw_ms <= 0.0:
            return pw_ms
        pw = pw_ms
        if self.dp_x and isfinite(dp_kpa) and dp_kpa > 0.0:
            useful = pw - dead_ms
            if useful > 0.0:
                factor = interp1(self.dp_x, self.dp_factor, dp_kpa)
                core_factor = sqrt(dp_kpa / self.ref_kpa)
                if factor > 0.0:
                    pw = dead_ms + useful * core_factor / factor
        if self.adder_x:
            pw += interp1(self.adder_x, self.adder_ms, pw_ms)
        return pw if pw > 0.0 else 0.0
