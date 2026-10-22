"""Temperaturas lumpadas (ECT, óleo, pistão, ponto quente) e pressão de óleo (RF-24; D-BUS-03).

Todos os modelos são de 1.ª ordem com constantes inferidas (a validar); servem à
repetibilidade térmica entre puxadas e às entradas que a ECU e o dano consomem.
"""

from __future__ import annotations

import math

__all__ = [
    "CoolantModel",
    "hot_spot_target_c",
    "oil_pressure_kpa",
    "oil_temp_rate",
    "piston_target_c",
    "relax",
]

PISTON_TAU_S = 8.0
HOT_SPOT_TAU_S = 2.0
PISTON_HEAT_SHARE = 0.30  # fração do calor de parede que passa pela coroa do pistão
PISTON_HA_W_K = 45.0  # condutância coroa → óleo/camisa (inferido)
HOT_SPOT_EGT_SHARE = 0.75  # ponto quente (vela/válvula de escape) entre ECT e a EGT
OIL_TAU_S = 90.0
OIL_LOAD_RISE_K = 15.0
OIL_RELIEF_KPA = 550.0
OIL_BASE_KPA = 60.0
OIL_GAIN_KPA_PER_RPM = 0.085


def relax(value: float, target: float, dt: float, tau: float) -> float:
    """Passo exato de 1.ª ordem ``x + (1 − e^(−dt/τ))·(alvo − x)``."""
    return value + (1.0 - math.exp(-dt / tau)) * (target - value)


def piston_target_c(ect_c: float, wall_heat_w: float) -> float:
    """Temperatura de regime da coroa do pistão (°C) pelo fluxo de calor do cilindro."""
    return ect_c + PISTON_HEAT_SHARE * max(wall_heat_w, 0.0) / PISTON_HA_W_K


def hot_spot_target_c(ect_c: float, egt_c: float, firing: bool) -> float:
    """Ponto quente de regime (°C): fração da distância ECT → EGT do cilindro."""
    if not firing:
        return ect_c
    return ect_c + HOT_SPOT_EGT_SHARE * max(egt_c - ect_c, 0.0)


def oil_temp_rate(oil_c: float, ect_c: float, load_fraction: float) -> float:
    """``dT_oil/dt`` (K/s): segue a ECT com τ 90 s e sobe com a carga."""
    target = ect_c + OIL_LOAD_RISE_K * min(max(load_fraction, 0.0), 1.0)
    return (target - oil_c) / OIL_TAU_S


def oil_pressure_kpa(rpm: float, oil_c: float, locked: bool) -> float:
    """Pressão de óleo simplificada (kPa relativa, D-BUS-03).

    ``p = min(p_alívio, (60 + 0,085 · rpm) · f_visc)``, ``f_visc = clip(1 + 0,006·(90 − T_oil),
    0,8, 1,6)``; 0 com o motor parado ou bloqueado; rampa linear abaixo de 400 rpm.
    """
    if locked or rpm <= 0.0:
        return 0.0
    f_visc = min(max(1.0 + 0.006 * (90.0 - oil_c), 0.8), 1.6)
    p = min(OIL_RELIEF_KPA, (OIL_BASE_KPA + OIL_GAIN_KPA_PER_RPM * rpm) * f_visc)
    if rpm < 400.0:  # noqa: PLR2004
        p *= rpm / 400.0
    return p


class CoolantModel:
    """ECT lumpada com termóstato e radiador sob o ventilador da bancada.

    ``C · dECT/dt = f_cool · Q̇_parede − UA(ventilador, termóstato) · (ECT − T_amb)``.
    """

    CAPACITY_J_K = 60_000.0
    COOLANT_SHARE = 0.5
    UA_BASE_W_K = 30.0
    UA_RADIATOR_W_K = 300.0
    UA_FAN_W_K_PER_M_S = 80.0
    THERMOSTAT_OPEN_C = 88.0
    THERMOSTAT_FULL_C = 98.0

    def rate(self, ect_c: float, wall_heat_w: float, t_amb_c: float, fan_m_s: float) -> float:
        span = self.THERMOSTAT_FULL_C - self.THERMOSTAT_OPEN_C
        opening = min(max((ect_c - self.THERMOSTAT_OPEN_C) / span, 0.0), 1.0)
        ua = self.UA_BASE_W_K + opening * (self.UA_RADIATOR_W_K + self.UA_FAN_W_K_PER_M_S * fan_m_s)
        q_in = self.COOLANT_SHARE * max(wall_heat_w, 0.0)
        return (q_in - ua * (ect_c - t_amb_c)) / self.CAPACITY_J_K
