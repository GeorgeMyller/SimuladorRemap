"""Combustível flex: mistura E27/E100 com teor de etanol fixo por sessão (RF-18; D-08).

``blend_fuel(e27, e100, ethanol_pct)`` devolve um ``FuelSpec`` com ``fuel_id = "flex"``,
calculado uma vez na criação da sessão (sem custo por tick). O peso da mistura é
``t = (pct − 27) / (100 − 27)``; a fração mássica de etanol interpola entre as âncoras
(``ethanol_mass_fraction`` de E27 e E100) com o mesmo ``t``:

- ``1/AFR`` linear em ``t`` (o oxigênio do etanol soma-se em massa);
- PCI, ``h_fg``, densidade, parâmetros de velocidade laminar e temperatura de
  pré-ignição lineares em ``t``;
- RON, MON e ON de knock por curva côncava ``1 − (1 − t)²`` (o etanol rende mais
  octanagem nas primeiras frações).
"""

from __future__ import annotations

from typing import Final

from simremap.catalog.contracts import FLEX_FUEL_ID, FuelSpec

__all__ = [
    "ETHANOL_PCT_MAX",
    "ETHANOL_PCT_MIN",
    "blend_afr_stoich",
    "blend_density",
    "blend_fuel",
    "blend_weight",
]

ETHANOL_PCT_MIN: Final = 27.0  # % da âncora E27
ETHANOL_PCT_MAX: Final = 100.0  # % da âncora E100


def blend_weight(ethanol_pct: float) -> float:
    """Peso ``t`` da âncora E100 (0 em E27, 1 em E100); ``ValueError`` fora de 27–100 %."""
    if not ETHANOL_PCT_MIN <= ethanol_pct <= ETHANOL_PCT_MAX:
        raise ValueError(
            f"ethanol_pct {ethanol_pct} fora de {ETHANOL_PCT_MIN:g}–{ETHANOL_PCT_MAX:g} %"
        )
    return (ethanol_pct - ETHANOL_PCT_MIN) / (ETHANOL_PCT_MAX - ETHANOL_PCT_MIN)


def blend_afr_stoich(ethanol_pct: float, afr_e27: float, afr_e100: float) -> float:
    """AFR estequiométrico da mistura: ``1/AFR`` linear no peso (usado pela física e pela ECU)."""
    t = blend_weight(min(max(ethanol_pct, ETHANOL_PCT_MIN), ETHANOL_PCT_MAX))
    return 1.0 / ((1.0 - t) / afr_e27 + t / afr_e100)


def _lerp(low: float, high: float, t: float) -> float:
    return low + (high - low) * t


def blend_density(ethanol_pct: float, density_e27: float, density_e100: float) -> float:
    """Densidade da mistura (linear no peso; mesma unidade das âncoras)."""
    t = blend_weight(min(max(ethanol_pct, ETHANOL_PCT_MIN), ETHANOL_PCT_MAX))
    return _lerp(density_e27, density_e100, t)


def _concave(low: float, high: float, t: float) -> float:
    return low + (high - low) * (1.0 - (1.0 - t) ** 2)


def blend_fuel(e27: FuelSpec, e100: FuelSpec, ethanol_pct: float) -> FuelSpec:
    """``FuelSpec`` ``flex`` com ``ethanol_pct`` (27–100 %) de etanol."""
    t = blend_weight(ethanol_pct)
    return FuelSpec(
        fuel_id=FLEX_FUEL_ID,
        display_name=f"Flex E{ethanol_pct:g}",
        afr_stoich=blend_afr_stoich(ethanol_pct, e27.afr_stoich, e100.afr_stoich),
        lhv_mj_kg=_lerp(e27.lhv_mj_kg, e100.lhv_mj_kg, t),
        ron=_concave(e27.ron, e100.ron, t),
        mon=_concave(e27.mon, e100.mon, t),
        knock_on=_concave(e27.knock_on, e100.knock_on, t),
        h_fg_kj_kg=_lerp(e27.h_fg_kj_kg, e100.h_fg_kj_kg, t),
        density_kg_m3=blend_density(ethanol_pct, e27.density_kg_m3, e100.density_kg_m3),
        ethanol_mass_fraction=_lerp(e27.ethanol_mass_fraction, e100.ethanol_mass_fraction, t),
        laminar_bm_m_s=_lerp(e27.laminar_bm_m_s, e100.laminar_bm_m_s, t),
        laminar_bphi_m_s=_lerp(e27.laminar_bphi_m_s, e100.laminar_bphi_m_s, t),
        laminar_phi_m=_lerp(e27.laminar_phi_m, e100.laminar_phi_m, t),
        preignition_surface_temp_c=_lerp(
            e27.preignition_surface_temp_c, e100.preignition_surface_temp_c, t
        ),
    )
