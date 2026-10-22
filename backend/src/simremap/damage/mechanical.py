"""Dano mecânico: biela, válvulas, bronzinas, turbina e junta (RF-14 a RF-17; D-21).

Os limites estruturais vêm do ``vehicle-catalog`` (``MechanicalLimits``) e são
convertidos internamente: ``F_lim_n = 1000 · max_rod_load_kn`` e
``p_lim_kpa = 100 · max_cylinder_pressure_bar``. Limite ausente ⇒
``DAMAGE_CONFIG_INVALID`` (EC-11), sem valor padrão inventado.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from simremap.catalog.contracts import VehicleSpec
from simremap.damage.config import DamageConfig
from simremap.damage.errors import DamageError

__all__ = [
    "StructuralLimits",
    "bearing_overrev_rate",
    "draw_rod_weights",
    "peak_pressure_damage",
    "rod_damage",
    "rod_load_ratio",
    "turbo_overspeed",
    "valve_overrev",
]

_REQUIRED_LIMITS = (
    "rod_torque_limit_nm",
    "max_rod_load_kn",
    "max_cylinder_pressure_bar",
    "egt_max_c",
    "max_rpm",
    "valve_float_rpm",
    "max_piston_temp_c",
)


@dataclass(frozen=True, slots=True)
class StructuralLimits:
    """Limites do veículo já convertidos para N e kPa."""

    rod_torque_limit_nm: float  # N·m
    rod_force_limit_n: float  # N (F_lim_n)
    cylinder_pressure_limit_kpa: float  # kPa (p_lim_kpa)
    egt_limit_c: float  # °C pré-turbina
    max_rpm: float  # rev/min
    valve_float_rpm: float  # rev/min
    max_piston_temp_c: float  # °C
    turbo_max_rpm: float | None  # rev/min; None sem turbo
    n_cyl: int
    bore_mm: float
    injection_type: str

    @property
    def has_turbo(self) -> bool:
        return self.turbo_max_rpm is not None

    @classmethod
    def from_vehicle(cls, vehicle: VehicleSpec) -> StructuralLimits:
        """Lê e converte os limites; ``DAMAGE_CONFIG_INVALID`` se algum faltar (EC-11)."""
        limits = vehicle.mechanical_limits
        for name in _REQUIRED_LIMITS:
            value = getattr(limits, name, None)
            if value is None or not math.isfinite(float(value)):
                raise DamageError(
                    f"Limite mecânico ausente no catálogo: mechanical_limits.{name}",
                    code="DAMAGE_CONFIG_INVALID",
                    field=f"mechanical_limits.{name}",
                )
        turbo_max = limits.turbo_max_rpm if vehicle.induction == "turbo" else None
        if vehicle.induction == "turbo" and turbo_max is None:
            raise DamageError(
                "Limite mecânico ausente no catálogo: mechanical_limits.turbo_max_rpm",
                code="DAMAGE_CONFIG_INVALID",
                field="mechanical_limits.turbo_max_rpm",
            )
        return cls(
            rod_torque_limit_nm=float(limits.rod_torque_limit_nm),
            rod_force_limit_n=1000.0 * float(limits.max_rod_load_kn),
            cylinder_pressure_limit_kpa=100.0 * float(limits.max_cylinder_pressure_bar),
            egt_limit_c=float(limits.egt_max_c),
            max_rpm=float(limits.max_rpm),
            valve_float_rpm=float(limits.valve_float_rpm),
            max_piston_temp_c=float(limits.max_piston_temp_c),
            turbo_max_rpm=None if turbo_max is None else float(turbo_max),
            n_cyl=vehicle.engine.n_cyl,
            bore_mm=vehicle.engine.bore_mm,
            injection_type=vehicle.engine.injection_type,
        )


def draw_rod_weights(rng: np.random.Generator, n_cyl: int, config: DamageConfig) -> list[float]:
    """``w_i ~ U(0,9; 1,1)`` sorteados uma vez por sessão (substream ``rod_weights``)."""
    low, high = config.rod_weight_range
    return [float(v) for v in rng.uniform(low, high, size=n_cyl)]


def rod_load_ratio(torque_nm: float, rod_force_peak_n: float, limits: StructuralLimits) -> float:
    """``r_i = max(torque / rod_torque_limit, F_i / F_lim_n)``."""
    return max(torque_nm / limits.rod_torque_limit_nm, rod_force_peak_n / limits.rod_force_limit_n)


def rod_damage(ratio: float, weight: float, config: DamageConfig) -> tuple[float, bool]:
    """RF-14: ``(ΔD, falha_imediata)``; sem dano com ``r < 1``."""
    if ratio >= config.rod_instant_ratio:
        return 1.0, True
    if ratio < 1.0:
        return 0.0, False
    return config.rod_damage_base * (1.0 + config.rod_damage_slope * (ratio - 1.0)) * weight, False


def valve_overrev(rpm: float, limits: StructuralLimits, config: DamageConfig) -> tuple[float, bool]:
    """RF-15: ``(ΔD por ciclo, contato válvula-pistão)`` acima de ``valve_float_rpm``."""
    if rpm >= config.valve_contact_ratio * limits.valve_float_rpm:
        return 1.0, True
    if rpm <= limits.valve_float_rpm:
        return 0.0, False
    return config.valve_float_damage_per_100rpm * (rpm - limits.valve_float_rpm) / 100.0, False


def bearing_overrev_rate(rpm: float, limits: StructuralLimits, config: DamageConfig) -> float:
    """RF-15: ``dD/dt = 0,4 · (rpm / max_rpm − 1)`` por segundo acima de ``max_rpm``."""
    if rpm <= limits.max_rpm:
        return 0.0
    return config.bearing_overrev_rate * (rpm / limits.max_rpm - 1.0)


def turbo_overspeed(
    turbo_rpm: float | None, limits: StructuralLimits, config: DamageConfig
) -> tuple[float, bool]:
    """RF-16: ``(dD/dt por segundo, burst)``; nada sem turbo (EC-12)."""
    if limits.turbo_max_rpm is None or turbo_rpm is None:
        return 0.0, False
    ratio = turbo_rpm / limits.turbo_max_rpm
    if ratio >= config.turbo_burst_ratio:
        return 0.0, True
    if ratio <= 1.0:
        return 0.0, False
    return config.turbo_overspeed_rate * (ratio - 1.0), False


def peak_pressure_damage(p_max_kpa: float, limits: StructuralLimits, config: DamageConfig) -> float:
    """RF-17: ``ΔD = 0,01 · (p_max / p_lim − 1)`` por ciclo acima do limite."""
    excess = p_max_kpa / limits.cylinder_pressure_limit_kpa - 1.0
    return config.peak_pressure_damage * excess if excess > 0.0 else 0.0
