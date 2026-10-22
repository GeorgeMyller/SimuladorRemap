"""Conversões de potência entre cambota e roda (vehicle-catalog RF-18; seção 8).

``crank_to_wheel_kw(v, p) = p · η_drv − P_fixa`` e
``wheel_to_crank_kw(v, p) = (p + P_fixa) / η_drv``; ``whp = kW / 0,7457``.
São as mesmas relações usadas pelo ``dyno-bench`` (``P_crank = P_wheel / η_drv`` com
perda fixa padrão 0 kW) e pela validação RF-13 das curvas de referência.
"""

from __future__ import annotations

import math
from typing import Protocol

from simremap.catalog.contracts import KW_PER_HP

__all__ = [
    "DrivetrainLosses",
    "crank_power_kw",
    "crank_to_wheel_kw",
    "kw_to_whp",
    "wheel_to_crank_kw",
    "whp_to_kw",
]


class DrivetrainLosses(Protocol):
    """Campos de perdas de transmissão (``VehicleSpec`` cumpre este protocolo)."""

    @property
    def drivetrain_efficiency(self) -> float: ...

    @property
    def drivetrain_fixed_loss_kw(self) -> float: ...


def crank_power_kw(torque_nm: float, rpm: float) -> float:
    """``P = T · 2π · rpm / 60 / 1000`` (kW)."""
    return torque_nm * 2.0 * math.pi * rpm / 60.0 / 1000.0


def crank_to_wheel_kw(vehicle: DrivetrainLosses, power_crank_kw: float) -> float:
    """Potência na roda (kW) a partir da potência na cambota (kW)."""
    return power_crank_kw * vehicle.drivetrain_efficiency - vehicle.drivetrain_fixed_loss_kw


def wheel_to_crank_kw(vehicle: DrivetrainLosses, power_wheel_kw: float) -> float:
    """Potência na cambota (kW) a partir da potência na roda (kW)."""
    return (power_wheel_kw + vehicle.drivetrain_fixed_loss_kw) / vehicle.drivetrain_efficiency


def kw_to_whp(power_kw: float) -> float:
    return power_kw / KW_PER_HP


def whp_to_kw(power_whp: float) -> float:
    return power_whp * KW_PER_HP
