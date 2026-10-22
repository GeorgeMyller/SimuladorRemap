"""Correção de potência SAE J1349, DIN 70020 ou nenhuma (dyno RF-10; D-29).

O fator é constante por puxada, porque o ambiente da sessão é fixo (seção 15 da spec):

- pressão de vapor (Magnus): ``p_sat = 0,61094 · exp(17,625 · T / (T + 243,04))`` kPa,
  ``p_v = RH · p_sat`` e pressão seca ``p_d = p_baro − p_v``;
- SAE J1349: ``CF = 1,18 · (99 / p_d) · sqrt((T + 273,15) / 298,15) − 0,18``;
- DIN 70020: ``CF = (101,325 / p_baro) · sqrt((T + 273,15) / 293,15)``;
- ``none``: ``CF = 1,0``.

O fator é limitado a 0,90..1,10; fora da faixa a puxada grava
``correction_out_of_range = true`` e aplica o valor limitado (EC-08).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from simremap.dyno.contracts import AmbientConditions, CorrectionStandard

__all__ = [
    "CF_MAX",
    "CF_MIN",
    "CorrectionResult",
    "correction_factor",
    "dry_pressure_kpa",
    "raw_correction_factor",
    "vapor_pressure_kpa",
]

CF_MIN: Final = 0.90
CF_MAX: Final = 1.10
K0: Final = 273.15
SAE_REF_DRY_KPA: Final = 99.0
SAE_REF_T_K: Final = 298.15
DIN_REF_KPA: Final = 101.325
DIN_REF_T_K: Final = 293.15


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    """Fator aplicado (limitado), fator bruto e indicação de saturação."""

    factor: float
    raw_factor: float
    out_of_range: bool
    standard: CorrectionStandard


def vapor_pressure_kpa(temperature_c: float, relative_humidity: float) -> float:
    """Pressão parcial de vapor ``p_v = RH · p_sat(T)`` pela fórmula de Magnus (kPa)."""
    p_sat = 0.61094 * math.exp(17.625 * temperature_c / (temperature_c + 243.04))
    return relative_humidity * p_sat


def dry_pressure_kpa(ambient: AmbientConditions) -> float:
    """Pressão do ar seco ``p_d = p_baro − p_v`` (kPa)."""
    return ambient.pressure_kpa - vapor_pressure_kpa(
        ambient.temperature_c, ambient.relative_humidity
    )


def raw_correction_factor(standard: CorrectionStandard, ambient: AmbientConditions) -> float:
    """Fator de correção antes do limite 0,90..1,10."""
    t_k = ambient.temperature_c + K0
    if standard == CorrectionStandard.SAE_J1349:
        p_d = dry_pressure_kpa(ambient)
        return 1.18 * (SAE_REF_DRY_KPA / p_d) * math.sqrt(t_k / SAE_REF_T_K) - 0.18
    if standard == CorrectionStandard.DIN_70020:
        return (DIN_REF_KPA / ambient.pressure_kpa) * math.sqrt(t_k / DIN_REF_T_K)
    return 1.0


def correction_factor(standard: CorrectionStandard, ambient: AmbientConditions) -> CorrectionResult:
    """Fator da puxada (limitado a 0,90..1,10) e ``correction_out_of_range``."""
    raw = raw_correction_factor(standard, ambient)
    clamped = min(max(raw, CF_MIN), CF_MAX)
    return CorrectionResult(
        factor=clamped,
        raw_factor=raw,
        out_of_range=not (CF_MIN <= raw <= CF_MAX),
        standard=standard,
    )
