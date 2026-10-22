"""Pedidos das estratégias e arbitragem determinística (ecu-core RF-23, RF-24, Apêndice C; RN-17).

Prioridade: failsafe (1) > limitador (2) > two-step/antilag/powershift (3) > overrun (4)
> normal (5). Regras de combinação (RF-24):

- máscaras de corte por OU lógico entre os níveis não inibidos;
- um nível com corte TOTAL (todos os cilindros, combustível ou faísca) inibe os níveis
  de menor prioridade (C-01, C-02); cortes parciais e pedidos sem corte combinam (C-07,
  C-08);
- override absoluto de ignição: o do nível de maior prioridade que o pede; empate no
  mesmo nível: o menor avanço. O avanço final do cilindro é ``min(override, normal)``,
  com ``normal`` já descontado do retardo de knock (C-03);
- retardos relativos (limitador soft, retomada do powershift, failsafe): o maior;
- lambda alvo: o mais rico entre os pedidos absolutos e ``λ_base + Δλ`` do failsafe (C-05);
- teto de boost: o mínimo dos tetos; ``boost_cut`` por OU (duty 0 %, C-06).

Os objetos são pré-alocados e reutilizados a cada tick (sem alocação no hot path, além
da lista de nomes ativos).
"""

from __future__ import annotations

from math import inf, isnan, nan
from typing import Final

__all__ = [
    "LEVELS",
    "ArbitrationResult",
    "EcuRequests",
    "StrategyRequest",
    "arbitrate",
]

LEVELS: Final[dict[str, int]] = {
    "failsafe": 1,
    "rev_limiter": 2,
    "two_step": 3,
    "antilag": 3,
    "powershift": 3,
    "overrun": 4,
}


class StrategyRequest:
    """Pedido de uma estratégia num tick (reiniciado por ``reset``)."""

    __slots__ = (
        "_false",
        "active",
        "antilag_air_pct",
        "boost_ceiling_kpa",
        "boost_cut",
        "fuel_cut",
        "has_cut",
        "ign_override",
        "ign_retard",
        "inhibited",
        "lambda_delta",
        "lambda_target",
        "level",
        "n_cyl",
        "name",
        "spark_cut",
    )

    def __init__(self, name: str, n_cyl: int) -> None:
        self.name = name
        self.level = LEVELS[name]
        self.n_cyl = n_cyl
        self._false = [False] * n_cyl
        self.fuel_cut = [False] * n_cyl
        self.spark_cut = [False] * n_cyl
        self.reset()

    def reset(self) -> None:
        self.active = False
        self.inhibited = False
        self.has_cut = False
        self.fuel_cut[:] = self._false
        self.spark_cut[:] = self._false
        self.ign_override = nan  # ° BTDC absoluto; NaN = sem override
        self.ign_retard = 0.0  # ° relativo (≥ 0)
        self.lambda_target = nan  # (-) absoluto; NaN = sem pedido
        self.lambda_delta = 0.0  # Δλ sobre o lambda base (failsafe enrich, ≤ 0)
        self.boost_ceiling_kpa = inf  # kPa abs
        self.boost_cut = False
        self.antilag_air_pct = nan  # %

    def cut_all(self, kind: str) -> None:
        """Corte total por ``fuel_cut`` ou ``spark_cut`` (``rolling_cut`` usa faísca)."""
        mask = self.fuel_cut if kind == "fuel_cut" else self.spark_cut
        for k in range(self.n_cyl):
            mask[k] = True
        self.has_cut = True
        self.active = True

    def cut_pattern(self, kind: str, n_cut: int, counter: int) -> None:
        """Corte parcial de ``n_cut`` cilindros pelo padrão rotativo ``(contador + k) mod n``."""
        if n_cut <= 0:
            return
        n = self.n_cyl
        if n_cut >= n:
            self.cut_all(kind)
            return
        mask = self.fuel_cut if kind == "fuel_cut" else self.spark_cut
        for k in range(n):
            if (counter + k) % n < n_cut:
                mask[k] = True
        self.has_cut = True
        self.active = True

    @property
    def total_cut(self) -> bool:
        return self.has_cut and (all(self.fuel_cut) or all(self.spark_cut))


class EcuRequests:
    """Conjunto dos pedidos do tick, na ordem de prioridade (passado a ``adjust_requests``)."""

    __slots__ = (
        "antilag",
        "failsafe",
        "ordered",
        "overrun",
        "powershift",
        "rev_limiter",
        "two_step",
    )

    def __init__(self, n_cyl: int) -> None:
        self.failsafe = StrategyRequest("failsafe", n_cyl)
        self.rev_limiter = StrategyRequest("rev_limiter", n_cyl)
        self.two_step = StrategyRequest("two_step", n_cyl)
        self.antilag = StrategyRequest("antilag", n_cyl)
        self.powershift = StrategyRequest("powershift", n_cyl)
        self.overrun = StrategyRequest("overrun", n_cyl)
        self.ordered: tuple[StrategyRequest, ...] = (
            self.failsafe,
            self.rev_limiter,
            self.two_step,
            self.antilag,
            self.powershift,
            self.overrun,
        )

    def reset(self) -> None:
        for req in self.ordered:
            req.reset()


class ArbitrationResult:
    """Resultado combinado (reutilizado a cada tick)."""

    __slots__ = (
        "_false",
        "active",
        "antilag_air_pct",
        "boost_ceiling_kpa",
        "boost_cut",
        "fuel_cut",
        "ign_override",
        "ign_retard",
        "lambda_target",
        "n_cyl",
        "spark_cut",
        "winner",
    )

    def __init__(self, n_cyl: int) -> None:
        self.n_cyl = n_cyl
        self._false = [False] * n_cyl
        self.fuel_cut = [False] * n_cyl
        self.spark_cut = [False] * n_cyl
        self.active: list[str] = []
        self.winner = "normal"
        self.ign_override = nan
        self.ign_retard = 0.0
        self.lambda_target = nan
        self.boost_ceiling_kpa = inf
        self.boost_cut = False
        self.antilag_air_pct = 0.0


def arbitrate(  # noqa: PLR0912, PLR0915 - hot path desenrolado de propósito
    requests: EcuRequests, lambda_base: float, out: ArbitrationResult
) -> None:
    """Combina os pedidos em ``out`` (RF-23, RF-24)."""
    fuel = out.fuel_cut
    spark = out.spark_cut
    fuel[:] = out._false
    spark[:] = out._false
    active: list[str] = []
    winner = "normal"
    override = nan
    override_level = 0
    retard = 0.0
    lam = inf
    ceiling = inf
    boost_cut = False
    air = 0.0
    inhibit_below = 99
    n = out.n_cyl
    for req in requests.ordered:
        if not req.active:
            continue
        if req.level > inhibit_below:
            req.inhibited = True
            continue
        if winner == "normal":
            winner = req.name
        active.append(req.name)
        if req.has_cut:
            rf = req.fuel_cut
            rs = req.spark_cut
            for k in range(n):
                if rf[k]:
                    fuel[k] = True
                if rs[k]:
                    spark[k] = True
            if req.total_cut and req.level < inhibit_below:
                inhibit_below = req.level
        o = req.ign_override
        if not isnan(o):
            if override_level == 0:
                override = o
                override_level = req.level
            elif req.level == override_level and o < override:
                override = o
        retard = max(retard, req.ign_retard)
        if not isnan(req.lambda_target) and req.lambda_target < lam:
            lam = req.lambda_target
        if req.lambda_delta < 0.0 and lambda_base + req.lambda_delta < lam:
            lam = lambda_base + req.lambda_delta
        ceiling = min(ceiling, req.boost_ceiling_kpa)
        if req.boost_cut:
            boost_cut = True
        if not isnan(req.antilag_air_pct) and req.antilag_air_pct > air:
            air = req.antilag_air_pct
    out.active = active
    out.winner = winner
    out.ign_override = override
    out.ign_retard = retard
    out.lambda_target = lam if lam != inf else nan
    out.boost_ceiling_kpa = ceiling
    out.boost_cut = boost_cut
    out.antilag_air_pct = air
