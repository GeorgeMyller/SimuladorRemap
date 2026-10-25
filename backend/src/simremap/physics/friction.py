"""Trabalho, atrito de Chen-Flynn, torque e potências (Apêndice A.6; RF-11, RF-21)."""

from __future__ import annotations

import math

from simremap.catalog.contracts import ChenFlynnSpec

__all__ = [
    "KW_PER_HP",
    "brake_torque_nm",
    "chen_flynn_fmep_kpa",
    "engine_inertia_kg_m2",
    "imep_kpa",
    "pmep_kpa",
    "power_kw",
    "rpm_rate_per_s",
    "wheel_power_kw",
    "whp",
]

KW_PER_HP = 0.7457


def imep_kpa(work_j: float, vd_cyl_m3: float) -> float:
    """``IMEP_g = ∮ p dV / V_d,cyl`` (kPa)."""
    return work_j / vd_cyl_m3 / 1000.0


def pmep_kpa(p_exh_kpa: float, p_man_kpa: float) -> float:
    """``PMEP = p_exh − p_man`` (kPa; negativo = ganho com boost acima da contrapressão)."""
    return p_exh_kpa - p_man_kpa


def chen_flynn_fmep_kpa(spec: ChenFlynnSpec, p_max_kpa: float, piston_speed_m_s: float) -> float:
    """``FMEP = C + A · p_max + B · S̄p + Q · S̄p²`` (bar internamente, devolvido em kPa)."""
    p_max_bar = p_max_kpa / 100.0
    sp = piston_speed_m_s
    fmep_bar = spec.c_bar + spec.a * p_max_bar + spec.b_bar_s_m * sp + spec.q_bar_s2_m2 * sp * sp
    return fmep_bar * 100.0


def brake_torque_nm(
    imep_g_kpa: float,
    pmep: float,
    fmep: float,
    vd_total_m3: float,
    parasitic_kw: float = 0.0,
    omega_rad_s: float = 0.0,
) -> float:
    """``T_b = (IMEP_g − PMEP − FMEP) · 1000 · V_d / (4π) − P_sc · 1000 / ω`` (N·m)."""
    torque = (imep_g_kpa - pmep - fmep) * 1000.0 * vd_total_m3 / (4.0 * math.pi)
    if parasitic_kw > 0.0 and omega_rad_s > 1.0:
        torque -= parasitic_kw * 1000.0 / omega_rad_s
    return torque


def power_kw(torque_nm: float, rpm: float) -> float:
    """``P = T_b · ω / 1000`` com ``ω = 2π · rpm / 60`` (kW)."""
    return torque_nm * 2.0 * math.pi * rpm / 60.0 / 1000.0


def wheel_power_kw(crank_kw: float, drivetrain_efficiency: float, fixed_loss_kw: float) -> float:
    """``P_wheel = P · η_drv − P_fixa`` (kW)."""
    return crank_kw * drivetrain_efficiency - fixed_loss_kw


def whp(wheel_kw: float) -> float:
    """Potência na roda em hp (1 hp = 0,7457 kW)."""
    return wheel_kw / KW_PER_HP


def rpm_rate_per_s(torque_net_nm: float, inertia_total_kg_m2: float) -> float:
    """``dω/dt = ΣT / J`` convertido em rpm/s."""
    return torque_net_nm / inertia_total_kg_m2 * 60.0 / (2.0 * math.pi)


def engine_inertia_kg_m2(displacement_cc: float) -> float:
    """Inércia do motor + volante (kg·m²), estimada pela cilindrada (inferido, a validar).

    O ``EngineSpec`` não traz a inércia; usa-se ``J = 0,05 + 0,055 · V_d[L]``
    (≈ 0,16 kg·m² no 2,0 L e 0,32 kg·m² no V8 5,0).
    """
    return 0.05 + 0.055 * displacement_cc / 1000.0
