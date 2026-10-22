"""Turbo: eixo com inércia, mapas simplificados, wastegate por duty e intercooler (A.8; RF-14)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from simremap.catalog.contracts import CompressorMapSpec, IntercoolerSpec, TurboSpec
from simremap.physics.interp import Interp1D, Interp2D
from simremap.physics.manifold import R_AIR, orifice_flow

__all__ = [
    "CP_AIR",
    "CP_EXH",
    "GAMMA_EXH",
    "R_AIR",
    "R_EXH",
    "CompressorMap",
    "CompressorPoint",
    "IntercoolerModel",
    "TurbineModel",
    "compressor_inlet_flow_limit",
    "rad_s_to_rpm",
    "rpm_to_rad_s",
    "shaft_acceleration",
    "wastegate_target",
]

CP_AIR = 1005.0  # J/(kg·K)
CP_EXH = 1200.0  # J/(kg·K) (c_p,exh, A.7)
GAMMA_EXH = 1.33
R_EXH = 287.0
ETA_C_MIN = 0.45
# Linha de surge (inferido): ṁ_surge = 0,30 · ṁ_choke(N) · √min(N / N_design, 1). Abaixo de
# N_design a linha recua para fluxo baixo (PR − 1 ∝ ṁ^1,5, forma dos mapas reais); com a
# fração fixa, a plena carga a baixa rotação (PR 1,1–1,5) caía em surge na série (T033, B4).
SURGE_FLOW_FRACTION = 0.30
SURGE_PR_MIN = 1.05  # abaixo disto a elevação de pressão não sustenta a reversão do fluxo
SPEED_LINE_LINEAR = 0.98  # regularização da elipse perto de PR_0(N)
T_REF_K = 298.15
P_REF_KPA = 101.325
OMEGA_FLOOR = 500.0
# Sobrevelocidade (inferido): a linha de velocidade não cresce além de 1,05·N_max e a
# eficiência cai 4 %/% acima de N_max (piso 0,2) — limita o eixo com a wastegate presa.
OVERSPEED_LINE_CAP = 1.05
OVERSPEED_ETA_SLOPE = 4.0
OVERSPEED_ETA_FLOOR = 0.2  # rad/s, piso da divisão por ω na equação do eixo


def rpm_to_rad_s(rpm: float) -> float:
    return rpm * math.pi / 30.0


def rad_s_to_rpm(omega: float) -> float:
    return omega * 30.0 / math.pi


@dataclass(frozen=True, slots=True)
class CompressorPoint:
    mass_flow_kg_s: float
    corrected_flow_kg_s: float
    efficiency: float
    pr_zero_flow: float  # PR_0(N)
    surge_margin: float  # < 0 = surge
    power_w: float
    t_out_k: float


class CompressorMap:
    """Linha de velocidade elíptica e eficiência paraboloide (forma paramétrica de A.8)."""

    def __init__(self, spec: CompressorMapSpec) -> None:
        self.spec = spec
        self._table = Interp2D.from_grid(spec.table) if spec.table is not None else None

    def corrected_flow(self, pr: float, n_corr_rpm: float) -> tuple[float, float, float]:
        """``(ṁ_corr, ṁ_choke(N), PR_0(N))`` na linha de velocidade de ``N_corr``."""
        s = self.spec
        n_line = min(max(n_corr_rpm, 0.0), OVERSPEED_LINE_CAP * s.n_max_rpm)
        m_choke = s.m_choke_max_kg_s * (n_line / s.n_max_rpm) ** 0.8
        pr0 = 1.0 + (s.pr_design - 1.0) * (n_line / s.n_design_rpm) ** 2
        if self._table is not None:
            # Mapa tabelado: x = PR, y = rpm, z = ṁ_corr (kg/s).
            return max(self._table(pr, n_corr_rpm), 0.0), m_choke, pr0
        if pr <= 1.0:
            return m_choke, m_choke, pr0
        if pr0 <= 1.0:
            return 0.0, m_choke, pr0
        y = (pr - 1.0) / (pr0 - 1.0)
        if y >= 1.0:
            return 0.0, m_choke, pr0
        if y > SPEED_LINE_LINEAR:
            edge = math.sqrt(1.0 - SPEED_LINE_LINEAR**2)
            return m_choke * edge * (1.0 - y) / (1.0 - SPEED_LINE_LINEAR), m_choke, pr0
        return m_choke * math.sqrt(1.0 - y * y), m_choke, pr0

    def efficiency(self, m_corr: float, n_corr_rpm: float) -> float:
        s = self.spec
        eta = s.eta_max * (
            1.0
            - s.k1 * ((m_corr - s.m_peak_kg_s) / s.m_range_kg_s) ** 2
            - s.k2 * ((n_corr_rpm - s.n_peak_rpm) / s.n_max_rpm) ** 2
        )
        eta = min(max(eta, ETA_C_MIN), s.eta_max)
        over = n_corr_rpm / s.n_max_rpm - 1.0
        if over > 0.0:  # sobrevelocidade: a eficiência colapsa acima de N_max
            eta *= max(OVERSPEED_ETA_FLOOR, 1.0 - OVERSPEED_ETA_SLOPE * over)
        return eta

    def operate(self, pr: float, n_rpm: float, p01_kpa: float, t01_k: float) -> CompressorPoint:
        """Ponto de operação para a razão de pressão ``pr`` e rotação ``n_rpm``."""
        theta = t01_k / T_REF_K
        delta = p01_kpa / P_REF_KPA
        n_corr = n_rpm / math.sqrt(theta)
        m_corr, m_choke, pr0 = self.corrected_flow(pr, n_corr)
        m_dot = m_corr * delta / math.sqrt(theta)
        eta = self.efficiency(m_corr, n_corr)
        pr_eff = max(pr, 1.0)
        dt_ideal = t01_k * (pr_eff ** ((1.4 - 1.0) / 1.4) - 1.0)
        t_out = t01_k + dt_ideal / eta
        power = m_dot * CP_AIR * (t_out - t01_k)
        speed = min(max(n_corr, 0.0) / self.spec.n_design_rpm, 1.0)
        surge_line = SURGE_FLOW_FRACTION * m_choke * math.sqrt(speed)
        margin = (m_corr / surge_line - 1.0) if (surge_line > 0.0 and pr > SURGE_PR_MIN) else 1.0
        return CompressorPoint(m_dot, m_corr, eta, pr0, margin, power, t_out)


class TurbineModel:
    """Turbina como bocal e potência isentrópica com ``η_t(PR_t)`` (A.8)."""

    def __init__(self, spec: TurboSpec) -> None:
        self.spec = spec
        self.area_m2 = spec.turbine_area_eff_cm2 * 1e-4
        self.wg_area_max_m2 = spec.wastegate_area_max_cm2 * 1e-4
        self._eta = Interp1D.from_grid(spec.turbine_efficiency)

    def flow(self, p03_kpa: float, t03_k: float, p04_kpa: float) -> float:
        return max(
            orifice_flow(self.area_m2, p03_kpa, t03_k, p04_kpa, t03_k, GAMMA_EXH, R_EXH), 0.0
        )

    def wastegate_flow(self, x_wg: float, p03_kpa: float, t03_k: float, p04_kpa: float) -> float:
        area = self.wg_area_max_m2 * min(max(x_wg, 0.0), 1.0)
        return max(orifice_flow(area, p03_kpa, t03_k, p04_kpa, t03_k, GAMMA_EXH, R_EXH), 0.0)

    def power_w(self, m_t: float, p03_kpa: float, t03_k: float, p04_kpa: float) -> float:
        if m_t <= 0.0 or p03_kpa <= p04_kpa:
            return 0.0
        pr_t = p03_kpa / p04_kpa
        eta = self._eta(pr_t)
        expo = (GAMMA_EXH - 1.0) / GAMMA_EXH
        return float(m_t * CP_EXH * t03_k * eta * (1.0 - (1.0 / pr_t) ** expo))


def wastegate_target(
    p_boost_kpa: float, p_amb_kpa: float, duty_pct: float, spring_kpa: float, full_delta_kpa: float
) -> float:
    """``x_wg = clip((p_boost,rel · (1 − duty/100) − p_mola) / Δp_full, 0, 1)``."""
    p_act = (p_boost_kpa - p_amb_kpa) * (1.0 - duty_pct / 100.0)
    return min(max((p_act - spring_kpa) / full_delta_kpa, 0.0), 1.0)


def shaft_acceleration(
    omega: float, p_turb_w: float, p_comp_w: float, inertia: float, friction_k: float
) -> float:
    """``dω/dt`` de ``J · ω · dω/dt = P_turb − P_comp − k_f · ω²`` (piso de ω na divisão)."""
    drive = (p_turb_w - p_comp_w) / (inertia * max(omega, OMEGA_FLOOR))
    return drive - friction_k * omega / inertia


class IntercoolerModel:
    """``T_out = T_in − ε · (T_in − T_core)``; ``Δp = k · ṁ²``; núcleo com inércia térmica.

    O núcleo (``T_core``) aquece com a carga e arrefece para o ambiente com o ventilador da
    bancada; é ele que produz o heat soak entre puxadas (RF-24).
    """

    CAPACITY_J_K = 12000.0  # capacidade térmica do núcleo + tubagem (inferido)
    HA_BASE_W_K = 150.0  # convecção natural (inferido)
    HA_FAN_W_K_PER_M_S = 40.0  # ganho do ventilador (inferido)

    def __init__(self, spec: IntercoolerSpec | None) -> None:
        self.spec = spec
        self.effectiveness = spec.effectiveness if spec is not None else 0.0
        self.k_dp = spec.k_dp_kpa_per_kgps2 if spec is not None else 0.0

    def outlet_temp(self, t_in_k: float, t_core_k: float) -> float:
        return t_in_k - self.effectiveness * (t_in_k - t_core_k)

    def pressure_drop_kpa(self, m_dot: float) -> float:
        return self.k_dp * m_dot * m_dot

    def core_rate(
        self, t_core_k: float, t_in_k: float, m_dot: float, t_amb_k: float, fan_m_s: float
    ) -> float:
        """``dT_core/dt`` (K/s)."""
        if self.spec is None:
            return 0.0
        q_in = max(m_dot, 0.0) * CP_AIR * self.effectiveness * (t_in_k - t_core_k)
        ha = self.HA_BASE_W_K + self.HA_FAN_W_K_PER_M_S * fan_m_s
        return (q_in - ha * (t_core_k - t_amb_k)) / self.CAPACITY_J_K


def compressor_inlet_flow_limit(
    p_amb_kpa: float, t_amb_k: float, p_out_kpa: float, area: float
) -> float:
    """Escoamento passivo pelo compressor parado quando ``p_boost < p_amb`` (orifício)."""
    return max(orifice_flow(area, p_amb_kpa, t_amb_k, p_out_kpa, t_amb_k), 0.0)
