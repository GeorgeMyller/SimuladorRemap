"""Pré-ignição por ponto quente, LSPI e mega-knock (RF-07 a RF-09; Apêndices B.4 e B.5).

- Ponto quente: ``p = min(0,3; p0 · exp((T_hs − T_thr)/15) · f_iat · f_load)`` só com
  ``T_hs ≥ T_thr − 60 °C``; ``f_iat = clip(exp((IAT − 40)/20); 0,5; 4)``,
  ``f_load = (MAP / 200)²``.
- LSPI (só GDI, 1200 ≤ rpm ≤ 3000, IMEP ≥ 1500 kPa):
  ``p = min(2·10⁻³; 10⁻⁴ · (1 + (IMEP − 1500)/300)² · f_iat)``.
- Mega-knock: ``p_pi = p_max · (1 + 0,035 · (θ_pi − avanço))``, ``I = 0,25 · p_pi / 100``;
  runaway: × 3 na probabilidade do cilindro nos 10 ciclos seguintes.

Sorteios em ordem fixa por evento: ponto quente (substream ``preignition``), depois LSPI
(substream ``lspi``). Só se sorteia quando a probabilidade é positiva.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from simremap.damage.config import DamageConfig

__all__ = [
    "PreignitionKind",
    "PreignitionOutcome",
    "PreignitionState",
    "hot_spot_probability",
    "iat_factor",
    "load_factor",
    "lspi_probability",
    "mega_knock_intensity",
    "preignition_pressure_kpa",
]

PreignitionKind = Literal["hot_spot", "lspi"]


def iat_factor(iat_c: float, config: DamageConfig) -> float:
    """``f_iat = clip(exp((IAT − 40)/20); 0,5; 4)``."""
    low, high = config.preignition_iat_clip
    value = math.exp((iat_c - config.preignition_iat_ref_c) / config.preignition_iat_scale_c)
    return min(high, max(low, value))


def load_factor(map_kpa: float, config: DamageConfig) -> float:
    """``f_load = (MAP / 200)²``."""
    return (max(0.0, map_kpa) / config.preignition_map_ref_kpa) ** 2


def hot_spot_probability(
    t_hot_spot_c: float, threshold_c: float, iat_c: float, map_kpa: float, config: DamageConfig
) -> float:
    """Probabilidade base de pré-ignição por ponto quente num ciclo (RF-07)."""
    if t_hot_spot_c < threshold_c - config.preignition_window_c:
        return 0.0
    raw = (
        config.preignition_p0
        * math.exp((t_hot_spot_c - threshold_c) / config.preignition_dt_scale_c)
        * iat_factor(iat_c, config)
        * load_factor(map_kpa, config)
    )
    return min(config.preignition_p_max, raw)


def lspi_probability(
    injection_type: str, rpm: float, imep_kpa: float, iat_c: float, config: DamageConfig
) -> float:
    """Probabilidade base de LSPI num ciclo (RF-08); 0 fora de GDI ou da janela."""
    low, high = config.lspi_rpm_range
    if (
        not config.lspi_enabled
        or injection_type != "gdi"
        or not low <= rpm <= high
        or imep_kpa < config.lspi_imep_min_kpa
    ):
        return 0.0
    growth = 1.0 + (imep_kpa - config.lspi_imep_min_kpa) / config.lspi_imep_scale_kpa
    return min(config.lspi_p_max, config.lspi_p_base * growth * growth * iat_factor(iat_c, config))


def preignition_pressure_kpa(
    p_max_kpa: float, theta_pi_btdc: float, advance_deg_btdc: float, config: DamageConfig
) -> float:
    """``p_pi = p_max · (1 + 0,035 · (θ_pi − avanço))`` (nunca abaixo de ``p_max``)."""
    factor = 1.0 + config.preignition_pressure_slope * (theta_pi_btdc - advance_deg_btdc)
    return p_max_kpa * max(1.0, factor)


def mega_knock_intensity(p_pi_kpa: float, config: DamageConfig) -> float:
    """``I = 0,25 · p_pi / 100`` (bar)."""
    return config.mega_knock_intensity_factor * p_pi_kpa / 100.0


@dataclass(frozen=True, slots=True)
class PreignitionOutcome:
    kind: PreignitionKind
    theta_pi_btdc: float
    probability: float  # probabilidade efetiva usada no sorteio


class PreignitionState:
    """Runaway por cilindro e sorteios semeados de ponto quente e LSPI."""

    __slots__ = ("_config", "_rng_hot", "_rng_lspi", "runaway")

    def __init__(
        self,
        n_cyl: int,
        config: DamageConfig,
        rng_hot_spot: np.random.Generator,
        rng_lspi: np.random.Generator,
    ) -> None:
        self._config = config
        self._rng_hot = rng_hot_spot
        self._rng_lspi = rng_lspi
        self.runaway = [0] * n_cyl

    def multiplier(self, cylinder: int) -> float:
        """× 3 enquanto o cilindro estiver em runaway."""
        return self._config.preignition_runaway_factor if self.runaway[cylinder - 1] > 0 else 1.0

    def evaluate(
        self, cylinder: int, p_hot_spot: float, p_lspi: float
    ) -> PreignitionOutcome | None:
        """Sorteia ponto quente e depois LSPI para o ciclo; atualiza o runaway."""
        index = cylinder - 1
        mult = self.multiplier(cylinder)
        if self.runaway[index] > 0:
            self.runaway[index] -= 1
        outcome: PreignitionOutcome | None = None
        p_hs = min(1.0, p_hot_spot * mult)
        if p_hs > 0.0 and float(self._rng_hot.random()) < p_hs:
            outcome = PreignitionOutcome("hot_spot", self._config.hot_spot_theta_btdc, p_hs)
        p_ls = min(1.0, p_lspi * mult)
        if p_ls > 0.0 and float(self._rng_lspi.random()) < p_ls and outcome is None:
            outcome = PreignitionOutcome("lspi", self._config.lspi_theta_btdc, p_ls)
        if outcome is not None:
            self.runaway[index] = self._config.preignition_runaway_cycles
        return outcome

    def reset(self) -> None:
        self.runaway = [0] * len(self.runaway)
