"""Detonação: Douaud-Eyzat, Livengood-Wu, MAPO, classes e dano por knock (RF-01 a RF-04, RF-11).

Equações (spec Apêndice A):

- ``τ = 17,68 · (ON/100)^3,402 · p_atm^(−1,7) · exp(3800 / T_u)`` em ms, com
  ``p_atm = p_kpa / 101,325`` e ``ON = (RON + MON)/2`` (premissa OQ-03);
- ``I_LW(θ_j) = Σ_{i ≤ j} Δt_deg / τ(θ_i)`` com ``Δt_deg = 1000 / (6 · rpm)`` ms por grau,
  desde a faísca (primeiro ponto do ``CombustionEvent``);
- knock no primeiro ``j`` com ``I_LW ≥ 1`` e ``x_b(θ_j) < x_b,end``;
- ``MAPO = c_mapo · (1 − x_b,k) · p_k`` (kPa), ``I = MAPO / 100`` (bar), ``E_k = f_ai · Q_disp``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from simremap.damage import native_bridge
from simremap.damage.config import DamageConfig
from simremap.damage.contracts import KnockClass, classify_knock
from simremap.damage.errors import DamageError
from simremap.physics.contracts import CombustionEvent

__all__ = [
    "ATM_KPA",
    "KnockResult",
    "douaud_eyzat_tau_ms",
    "evaluate_knock",
    "fuel_energy_j",
    "knock_piston_damage",
    "knock_temp_step",
    "livengood_wu_integral",
    "ms_per_degree",
    "octane_number",
    "validate_event",
]

ATM_KPA: Final = 101.325
DE_COEFF_MS: Final = 17.68
DE_ON_EXP: Final = 3.402
DE_P_EXP: Final = -1.7
DE_ACTIVATION_K: Final = 3800.0
MIN_RPM: Final = 1.0  # rev/min abaixo do qual não há ciclo a integrar


@dataclass(frozen=True, slots=True)
class KnockResult:
    """Resultado de Livengood-Wu e MAPO de um ciclo."""

    lw_integral_end: float  # I_LW no fim da combustão (-)
    theta_onset_deg_atdc: float | None  # θ_k (° ATDC)
    burned_fraction_onset: float | None  # x_b(θ_k)
    autoignited_fraction: float  # f_ai (-)
    mapo_kpa: float  # kPa
    intensity: float  # bar
    knock_energy_j: float  # J
    knock_class: KnockClass

    @classmethod
    def silent(cls, lw_integral_end: float = 0.0) -> KnockResult:
        return cls(lw_integral_end, None, None, 0.0, 0.0, 0.0, 0.0, KnockClass.NONE)


def octane_number(ron: float, mon: float) -> float:
    """``ON = (RON + MON) / 2`` (premissa OQ-03)."""
    return (ron + mon) / 2.0


def ms_per_degree(rpm: float) -> float:
    """``Δt_deg = 1000 / (6 · rpm)`` em ms por grau de cambota."""
    return 1000.0 / (6.0 * rpm)


def douaud_eyzat_tau_ms(
    pressure_kpa: NDArray[np.float64],
    t_unburned_k: NDArray[np.float64],
    octane: float,
    config: DamageConfig,
) -> NDArray[np.float64]:
    """Atraso de autoignição (ms) de Douaud-Eyzat, saturado em ``τ_sat`` (EC-03)."""
    p = np.asarray(pressure_kpa, dtype=np.float64)
    t = np.asarray(t_unburned_k, dtype=np.float64)
    valid = (t >= config.tau_min_temp_k) & (p >= config.tau_min_pressure_kpa)
    p_atm = np.where(valid, p, ATM_KPA) / ATM_KPA
    t_safe = np.where(valid, t, config.tau_min_temp_k)
    tau = (
        DE_COEFF_MS
        * config.knock_tau_multiplier
        * (octane / 100.0) ** DE_ON_EXP
        * np.power(p_atm, DE_P_EXP)
        * np.exp(DE_ACTIVATION_K / t_safe)
    )
    return np.where(valid, np.minimum(tau, config.tau_saturation_ms), config.tau_saturation_ms)


def livengood_wu_integral(tau_ms: NDArray[np.float64], rpm: float) -> NDArray[np.float64]:
    """Integral acumulada ``I_LW(θ_j)`` (1 ponto por grau)."""
    return np.cumsum(ms_per_degree(rpm) / tau_ms)


def validate_event(event: CombustionEvent) -> None:
    """EC-02: vetores com comprimentos diferentes ou não finitos ⇒ ``DAMAGE_INPUT_INVALID``."""
    n = len(event.pressure_kpa)
    if n != len(event.t_unburned_k) or n != len(event.burned_fraction):
        raise DamageError(
            f"CombustionEvent do cilindro {event.cylinder}: vetores com comprimentos diferentes",
            code="DAMAGE_INPUT_INVALID",
        )
    scalars = (event.rpm, event.p_max_kpa, event.rod_force_peak_n, event.imep_gross_kpa)
    if not all(math.isfinite(v) for v in scalars) or not _traces_finite(event):
        raise DamageError(
            f"CombustionEvent do cilindro {event.cylinder}: valor NaN ou infinito",
            code="DAMAGE_INPUT_INVALID",
        )


def fuel_energy_j(
    m_fuel_mg: float, m_air_mg: float, afr_stoich: float, lhv_mj_kg: float, eta_c: float
) -> float:
    """``Q_disp = η_c · min(m_fuel, m_air / AFR_st) · PCI`` em J (mg · MJ/kg = J)."""
    burnable_mg = max(0.0, min(m_fuel_mg, m_air_mg / afr_stoich))
    return eta_c * burnable_mg * lhv_mj_kg


def _traces_finite(event: CombustionEvent) -> bool:
    kernels = native_bridge.KERNELS
    if kernels is not None:
        return bool(
            kernels.traces_finite(event.pressure_kpa, event.t_unburned_k, event.burned_fraction)
        )
    return bool(
        np.isfinite(event.pressure_kpa).all()
        and np.isfinite(event.t_unburned_k).all()
        and np.isfinite(event.burned_fraction).all()
    )


def _knock_onset(event: CombustionEvent, octane: float, config: DamageConfig) -> tuple[float, int]:
    """``(I_LW no fim, 1.º índice com I_LW ≥ 1 ou -1)``; kernel nativo quando ativo."""
    kernels = native_bridge.KERNELS
    if kernels is not None:
        lw_end, k = kernels.knock_onset(
            event.pressure_kpa,
            event.t_unburned_k,
            event.rpm,
            octane,
            config.knock_tau_multiplier,
            config.tau_min_temp_k,
            config.tau_min_pressure_kpa,
            config.tau_saturation_ms,
        )
        return float(lw_end), int(k)
    pressure = np.asarray(event.pressure_kpa, dtype=np.float64)
    tau = douaud_eyzat_tau_ms(pressure, np.asarray(event.t_unburned_k), octane, config)
    integral = livengood_wu_integral(tau, event.rpm)
    candidates = np.flatnonzero(integral >= 1.0)
    return float(integral[-1]), int(candidates[0]) if candidates.size else -1


def evaluate_knock(event: CombustionEvent, q_disp_j: float, config: DamageConfig) -> KnockResult:
    """RF-01 a RF-04 sobre um ``CombustionEvent`` (misfire ou rpm 0 ⇒ intensidade 0)."""
    if event.misfire or event.rpm < MIN_RPM or not event.pressure_kpa:
        return KnockResult.silent()
    octane = octane_number(event.fuel_octane_ron, event.fuel_octane_mon)
    lw_end, k = _knock_onset(event, octane, config)
    if k < 0:
        return KnockResult.silent(lw_end)
    xb_k = float(event.burned_fraction[k])
    if xb_k >= config.xb_end:  # EC-04: a chama já consumiu a zona não queimada
        return KnockResult.silent(lw_end)
    f_ai = 1.0 - xb_k
    mapo = config.c_mapo * f_ai * float(event.pressure_kpa[k])
    intensity = mapo / 100.0
    return KnockResult(
        lw_integral_end=lw_end,
        theta_onset_deg_atdc=event.theta_start_deg + k,
        burned_fraction_onset=xb_k,
        autoignited_fraction=f_ai,
        mapo_kpa=mapo,
        intensity=intensity,
        knock_energy_j=f_ai * max(0.0, q_disp_j),
        knock_class=classify_knock(intensity),
    )


def knock_piston_damage(intensity: float, energy_j: float, config: DamageConfig) -> float:
    """RF-11: ``ΔD = c_k · max(0, I − I_safe) · (E_k / 100 J)`` no pistão."""
    return (
        config.c_knock
        * max(0.0, intensity - config.i_safe)
        * (energy_j / config.knock_energy_ref_j)
    )


def knock_temp_step(
    previous_c: float, last_intensity: float, dt: float, config: DamageConfig
) -> float:
    """B.1: ``ΔT_knock`` de 1ª ordem com alvo ``25 °C · max(0, I − 1)`` e τ 1,5 s."""
    target = config.knock_temp_gain_c * max(0.0, last_intensity - 1.0)
    alpha = 1.0 - math.exp(-dt / config.knock_temp_tau_s)
    return previous_c + alpha * (target - previous_c)
