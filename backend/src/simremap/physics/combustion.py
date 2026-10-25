"""Combustão: Wiebe, velocidade laminar de Metghalchi-Keck e duração (Apêndice A.4; RF-09)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from simremap.catalog.contracts import FuelSpec

__all__ = [
    "COMBUSTION_EFFICIENCY",
    "LAMBDA_MAX_FLAMMABLE",
    "LAMBDA_MIN_FLAMMABLE",
    "FlameCoefficients",
    "burn_duration_deg",
    "flammable",
    "ignition_delay_deg",
    "laminar_flame_speed",
    "reference_flame_speed",
    "wiebe_fraction",
    "wiebe_rate",
]

COMBUSTION_EFFICIENCY = 0.98  # η_c para 0,55 ≤ λ ≤ 1,6
LAMBDA_MIN_FLAMMABLE = 0.55
LAMBDA_MAX_FLAMMABLE = 1.6
IGNITION_DELAY_REF_DEG = 4.0  # Δθ_id a 3000 rpm
RESIDUAL_DURATION_GAIN = 2.2  # (1 + 2,2 · x_r)
RESIDUAL_SPEED_LOSS = 2.1  # (1 − 2,1 · x_r)
RPM_EXPONENT = 0.37
GASOLINE_BM, GASOLINE_BPHI, GASOLINE_PHIM = 0.305, -0.549, 1.21


@dataclass(frozen=True, slots=True)
class FlameCoefficients:
    """Coeficientes de Metghalchi-Keck lidos do ``FuelSpec`` (o catálogo mistura E/G)."""

    b_m: float  # m/s
    b_phi: float  # m/s
    phi_m: float  # (-)

    @classmethod
    def from_fuel(cls, fuel: FuelSpec) -> FlameCoefficients:
        return cls(fuel.laminar_bm_m_s, fuel.laminar_bphi_m_s, fuel.laminar_phi_m)


GASOLINE = FlameCoefficients(GASOLINE_BM, GASOLINE_BPHI, GASOLINE_PHIM)


def wiebe_fraction(theta: float, theta0: float, duration: float, a: float, m: float) -> float:
    """``x_b(θ) = 1 − exp(−a · ((θ − θ0)/Δθ)^(m+1))``; 0 antes de θ0, constante após o fim."""
    if theta <= theta0:
        return 0.0
    y = min((theta - theta0) / duration, 1.0)
    return 1.0 - math.exp(-a * y ** (m + 1.0))


def wiebe_rate(theta: float, theta0: float, duration: float, a: float, m: float) -> float:
    """``dx_b/dθ`` (1/grau); 0 fora de [θ0, θ0 + Δθ]."""
    if theta <= theta0 or theta > theta0 + duration:
        return 0.0
    y = (theta - theta0) / duration
    return float(a * (m + 1.0) / duration * y**m * math.exp(-a * y ** (m + 1.0)))


def laminar_flame_speed(
    coeffs: FlameCoefficients, lam: float, t_u_k: float, p_kpa: float, x_r: float
) -> float:
    """Velocidade laminar ``S_L`` (m/s) de Metghalchi-Keck com diluição por residual."""
    phi = 1.0 / lam
    s_l0 = coeffs.b_m + coeffs.b_phi * (phi - coeffs.phi_m) ** 2
    s_l0 = max(s_l0, 0.02)  # mistura muito fora da estequiometria: piso numérico
    alpha = 2.18 - 0.8 * (phi - 1.0)
    beta = -0.16 + 0.22 * (phi - 1.0)
    dilution = max(1.0 - RESIDUAL_SPEED_LOSS * x_r, 0.05)
    return float(s_l0 * (t_u_k / 298.0) ** alpha * (max(p_kpa, 1.0) / 101.325) ** beta * dilution)


def reference_flame_speed(t_u_k: float, p_kpa: float) -> float:
    """``S_L,ref``: gasolina E0, φ = 1, sem residual, no MESMO estado (T_u, p) do ciclo.

    Assim a razão ``S_L,ref / S_L`` isola os fatores que a spec lista para a duração
    (lambda, combustível e fração residual); o efeito de T e p quase se cancela.
    """
    return laminar_flame_speed(GASOLINE, 1.0, t_u_k, p_kpa, 0.0)


def burn_duration_deg(
    rpm: float,
    lam: float,
    coeffs: FlameCoefficients,
    x_r: float,
    t_u_k: float,
    p_kpa: float,
    duration_ref_deg: float = 55.0,
    rpm_ref: float = 3000.0,
) -> float:
    """``Δθ = Δθ_ref · (rpm/rpm_ref)^0,37 · (S_L,ref/S_L)^0,5 · (1 + 2,2·x_r)`` (graus)."""
    s_l = laminar_flame_speed(coeffs, lam, t_u_k, p_kpa, x_r)
    rpm_term = (max(rpm, 100.0) / rpm_ref) ** RPM_EXPONENT
    s_ref = reference_flame_speed(t_u_k, p_kpa)
    residual = 1 + RESIDUAL_DURATION_GAIN * x_r
    duration = duration_ref_deg * rpm_term * math.sqrt(s_ref / s_l) * residual
    return float(min(max(duration, 15.0), 140.0))


def ignition_delay_deg(rpm: float) -> float:
    """Atraso de inflamação ``Δθ_id = 4° · (rpm/3000)^0,5``."""
    return IGNITION_DELAY_REF_DEG * math.sqrt(max(rpm, 0.0) / 3000.0)


def flammable(lam: float) -> bool:
    """Mistura dentro dos limites de inflamabilidade (EC-05)."""
    return LAMBDA_MIN_FLAMMABLE <= lam <= LAMBDA_MAX_FLAMMABLE
