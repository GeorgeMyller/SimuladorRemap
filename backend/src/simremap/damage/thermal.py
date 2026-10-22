"""Dano térmico por Larson-Miller com a regra de Robinson e lambda pobre (RF-12, RF-13).

Apêndice B.2: ``LMP_ref = T_lim,K · (C + log10(t_ref_s / 3600))``,
``t_r(T) = 3600 · 10^(LMP_ref / T_K − C)`` s e ``ΔD = dt / t_r(T)`` só se ``T > T_lim``.
Dano zero no limite ou abaixo dele (decisão: integridade 100 % alcançável).

Temperatura de metal das válvulas e da turbina (calibração da integração física × dano):
``T_m,k = T_m,k−1 + (1 − exp(−dt/τ)) · (T_gás − T_m,k−1)``, inicializada na 1.ª amostra
(válvulas: ``min(EGT do cilindro, EGT do coletor)``, para um pico de arranque não virar
temperatura de metal; turbina: EGT do coletor). A
EGT de gás por cilindro da física tem picos de 1400–1800 °C em transitórios ricos de
décimos de segundo; a fluência acontece no metal, que responde em segundos.

Apêndice B.1: ``T_p,eff = piston_temp_c + ΔT_knock + ΔT_lean`` com
``ΔT_lean = 600 · max(0, λ − 0,88)`` só com MAP ≥ 150 kPa e λ conhecido.
"""

from __future__ import annotations

import math
from typing import Final

from simremap.damage.config import DamageConfig

__all__ = [
    "KELVIN",
    "creep_damage",
    "larson_miller_reference",
    "lean_delta_c",
    "metal_temp_step",
    "rupture_time_s",
]

KELVIN: Final = 273.15
SECONDS_PER_HOUR: Final = 3600.0


def larson_miller_reference(t_lim_c: float, t_ref_s: float, constant: float) -> float:
    """``LMP_ref = T_lim,K · (C + log10(t_ref_h))``."""
    return (t_lim_c + KELVIN) * (constant + math.log10(t_ref_s / SECONDS_PER_HOUR))


def rupture_time_s(temp_c: float, lmp_ref: float, constant: float) -> float:
    """``t_r(T) = 3600 · 10^(LMP_ref / T_K − C)`` em segundos."""
    exponent = lmp_ref / (temp_c + KELVIN) - constant
    return float(SECONDS_PER_HOUR * 10.0 ** min(exponent, 300.0))


def creep_damage(
    temp_c: float, limit_c: float, t_ref_s: float, dt: float, config: DamageConfig
) -> float:
    """Dano de fluência do passo (``dt / t_r``) acima do limite; 0 no limite ou abaixo."""
    if not temp_c > limit_c:
        return 0.0
    lmp = larson_miller_reference(limit_c, t_ref_s, config.lm_constant)
    return dt / rupture_time_s(temp_c, lmp, config.lm_constant)


def lean_delta_c(lambda_value: float | None, map_kpa: float, config: DamageConfig) -> float:
    """RF-13: ``ΔT_lean = k_lean · max(0, λ − 0,88)`` com MAP ≥ 150 kPa."""
    if lambda_value is None or map_kpa < config.lean_map_min_kpa:
        return 0.0
    return config.k_lean_c * max(0.0, lambda_value - config.lambda_lean_ref)


def metal_temp_step(previous_c: float, gas_c: float, dt: float, tau_s: float) -> float:
    """1ª ordem da temperatura de metal; ``previous_c`` NaN ⇒ inicializa no gás."""
    if math.isnan(previous_c):
        return gas_c
    return previous_c + (1.0 - math.exp(-dt / tau_s)) * (gas_c - previous_c)
