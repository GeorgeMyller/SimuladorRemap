"""EGT por balanço de energia de escape, cortes e pós-combustão (Apêndice A.7; RF-13, RF-22)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from simremap.physics.cycle_solver import gamma_of_t

__all__ = [
    "AFTERBURN_EFFICIENCY",
    "COLLECTOR_TAU_S",
    "CP_EXH_J_KG_K",
    "EGT_PROBE_UA_FRACTION",
    "POP_THRESHOLD_J",
    "PORT_EFFECTIVENESS",
    "PORT_GAS_MAX_K",
    "RICH_SINK_FRACTION",
    "ExhaustEvent",
    "blowdown_temperature",
    "exhaust_event",
    "first_order",
    "manifold_heat_loss",
]

CP_EXH_J_KG_K = 1200.0
AFTERBURN_EFFICIENCY = 0.6  # η_ab com O2 disponível
PORT_EFFECTIVENESS = 0.92  # ε_port
PORT_WALL_ABOVE_ECT_K = 150.0  # T_wall,port = ECT + 150 K (inferido)
PORT_GAS_MAX_K = 2400.0  # K, ≈ temperatura adiabática de chama da mistura (teto do gás)
COLLECTOR_TAU_S = 0.3
CYLINDER_GAS_TAU_S = 0.05  # suavização da EGT por cilindro entre eventos (inferido)
POP_THRESHOLD_J = 20.0
# Perda de calor nos runners/coletor até à turbina (inferido, calibrado com o benchmark v1):
# ``T_col = T_wall,exh + (T_mix − T_wall,exh) · exp(−UA / (ṁ · c_p,exh))``.
EXH_MANIFOLD_UA_W_K_PER_L23 = 24.0  # UA = 24 W/K · V_exh[L]^(2/3)
EXH_MANIFOLD_WALL_ABOVE_ECT_K = 250.0
# Sonda de EGT por cilindro no 1.º quarto do runner (inferido, integração física × dano):
# ``egt_c`` exposto = ``T_col`` acima com ``UA · 0,25 / n_cyl`` e o caudal do cilindro.
EGT_PROBE_UA_FRACTION = 0.25
MIN_FLOW_KG_S = 1e-6
# Sumidouro químico do combustível em excesso (λ < 1): fração do PCI do excesso que o
# escape rico absorve (dissociação/reforma endotérmica). Inferido e calibrado para que
# λ 0,80 reduza a EGT ≥ 30 °C face a λ 0,90 (RF-13).
RICH_SINK_FRACTION = 0.12


def first_order(y: float, x: float, dt: float, tau: float) -> float:
    """Filtro discreto ``y_k = y_{k−1} + (1 − e^(−dt/τ)) · (x_k − y_{k−1})``."""
    return y + (1.0 - math.exp(-dt / tau)) * (x - y)


def blowdown_temperature(t_evo_k: float, p_evo_kpa: float, p_exh_kpa: float) -> float:
    """``T_bd = T_evo · (p_exh / p_evo)^((γ − 1)/γ)`` (sem compressão se p_exh ≥ p_evo)."""
    if p_evo_kpa <= p_exh_kpa:
        return t_evo_k
    g = gamma_of_t(t_evo_k)
    return float(t_evo_k * (p_exh_kpa / p_evo_kpa) ** ((g - 1.0) / g))


@dataclass(frozen=True, slots=True)
class ExhaustEvent:
    t_port_k: float
    t_blowdown_k: float
    afterburn_dt_k: float
    afterfire_energy_j: float
    rich_sink_dt_k: float
    pop_event: bool


def exhaust_event(  # noqa: PLR0917
    t_evo_k: float,
    p_evo_kpa: float,
    p_exh_kpa: float,
    m_exh_kg: float,
    unburned_chem_j: float,
    excess_fuel_chem_j: float,
    oxygen_available: bool,
    ect_c: float,
) -> ExhaustEvent:
    """Temperatura na porta de escape de um evento (A.7).

    ``ΔT_ab = η_ab · Q_quim,esc / (m_exh · c_p,exh)`` só com O2 disponível;
    ``T_port = T_wall,port + (T_bd + ΔT_ab − ΔT_rico − T_wall,port) · ε_port``.
    """
    t_bd = blowdown_temperature(t_evo_k, p_evo_kpa, p_exh_kpa)
    m = max(m_exh_kg, 1e-9)
    energy = AFTERBURN_EFFICIENCY * unburned_chem_j if oxygen_available else 0.0
    dt_ab = energy / (m * CP_EXH_J_KG_K)
    dt_rich = (
        0.0 if oxygen_available else RICH_SINK_FRACTION * excess_fuel_chem_j / (m * CP_EXH_J_KG_K)
    )
    t_wall_port = ect_c + 273.15 + PORT_WALL_ABOVE_ECT_K
    # Teto físico: o gás na porta não passa da temperatura adiabática da pós-combustão
    # (integração: com massa de escape ínfima no arranque da bancada o ΔT_ab divergia
    # para > 4000 K e o laço abortava com NUMERIC_DIVERGENCE)
    t_gas = min(t_bd + dt_ab - dt_rich, PORT_GAS_MAX_K)
    t_port = t_wall_port + (t_gas - t_wall_port) * PORT_EFFECTIVENESS
    return ExhaustEvent(
        t_port_k=t_port,
        t_blowdown_k=t_bd,
        afterburn_dt_k=dt_ab,
        afterfire_energy_j=energy,
        rich_sink_dt_k=dt_rich,
        pop_event=energy > POP_THRESHOLD_J,
    )


def manifold_heat_loss(t_mix_k: float, m_dot_kg_s: float, ua_w_k: float, ect_c: float) -> float:
    """Temperatura à entrada da turbina após a perda nos runners (efetividade de troca)."""
    t_wall = ect_c + 273.15 + EXH_MANIFOLD_WALL_ABOVE_ECT_K
    if m_dot_kg_s <= MIN_FLOW_KG_S:
        return t_mix_k
    return t_wall + (t_mix_k - t_wall) * math.exp(-ua_w_k / (m_dot_kg_s * CP_EXH_J_KG_K))
