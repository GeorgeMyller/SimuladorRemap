"""Supercharger de deslocamento positivo (Roots ou twin-screw) (Apêndice A.9; RF-15)."""

from __future__ import annotations

from dataclasses import dataclass

from simremap.catalog.contracts import SuperchargerSpec
from simremap.physics.interp import Interp1D
from simremap.physics.manifold import R_AIR

__all__ = [
    "BYPASS_AREA_M2",
    "PRE_COMPRESSOR_PLENUM_M3",
    "SuperchargerModel",
    "SuperchargerPoint",
]

CP_AIR = 1005.0  # J/(kg·K)
ETA_V_MIN, ETA_V_MAX = 0.5, 0.98
BYPASS_AREA_M2 = 40e-4  # válvula de bypass ≈ 70 mm (inferido; PR → ≈ 1,02 com bypass aberto)
PRE_COMPRESSOR_PLENUM_M3 = 1.0e-3  # volume entre a borboleta e o rotor (pre_compressor, inferido)


@dataclass(frozen=True, slots=True)
class SuperchargerPoint:
    rotor_rpm: float
    mass_flow_kg_s: float
    volumetric_efficiency: float
    adiabatic_efficiency: float
    t_out_k: float
    power_kw: float  # perda parasita na cambota


class SuperchargerModel:
    """``ṁ = ρ_in · V_disp · N/60 · η_v``; ``P_sc = ṁ · c_p · (T_out − T_in) / η_mech``."""

    def __init__(self, spec: SuperchargerSpec) -> None:
        self.spec = spec
        self.disp_m3 = spec.displacement_l_per_rev * 1e-3
        self._eta_ad = Interp1D.from_grid(spec.adiabatic_efficiency)

    def rotor_rpm(self, engine_rpm: float) -> float:
        """``N_sc = rpm · pulley_ratio``."""
        return max(engine_rpm, 0.0) * self.spec.pulley_ratio

    def volumetric_efficiency(self, pr: float, n_sc: float) -> float:
        """``η_v = 1 − k_leak · (PR − 1) · N_ref / N_sc`` saturado em [0,5; 0,98]."""
        if n_sc <= 0.0:
            return ETA_V_MIN
        eta = 1.0 - self.spec.k_leak * (pr - 1.0) * self.spec.n_ref_rpm / n_sc
        return min(max(eta, ETA_V_MIN), ETA_V_MAX)

    def operate(
        self, engine_rpm: float, p_in_kpa: float, t_in_k: float, p_out_kpa: float
    ) -> SuperchargerPoint:
        n_sc = self.rotor_rpm(engine_rpm)
        pr = max(p_out_kpa, 1.0) / max(p_in_kpa, 1.0)
        eta_v = self.volumetric_efficiency(pr, n_sc)
        rho_in = 1000.0 * max(p_in_kpa, 0.0) / (R_AIR * t_in_k)
        m_dot = rho_in * self.disp_m3 * n_sc / 60.0 * eta_v
        eta_ad = self._eta_ad(max(pr, 1.0))
        pr_eff = max(pr, 1.0)
        t_out = t_in_k * (1.0 + (pr_eff ** (0.4 / 1.4) - 1.0) / eta_ad)
        power_kw = m_dot * CP_AIR * (t_out - t_in_k) / self.spec.mech_efficiency / 1000.0
        return SuperchargerPoint(n_sc, m_dot, eta_v, eta_ad, t_out, power_kw)
