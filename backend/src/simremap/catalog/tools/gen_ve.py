"""Geração da VE física estimada (vehicle-catalog Apêndice A.7).

Fórmula de autoria (determinística, só para gerar o arquivo)::

    VE(rpm, map) = clip(VE_pk · (1 − k_r · ((rpm − rpm_pk)/rpm_span)²)
                        · (1 − k_m · exp(−map/map_c)), 0,20, 1,35)

Com ``rpm_floor`` > 0 o termo em RPM usa ``max(rpm, rpm_floor)`` (forma plana em baixa
rotação, sem colapsar para o piso de 0,20 quando ``k_r`` é grande). Com ``rpm_span_high`` > 0
o ramo acima de ``rpm_pk`` usa esse vão no lugar de ``rpm_span`` (queda mais suave em alta
rotação: admissão e escape de fluxo alto com VVT nos dois comandos).

Eixos 16 × 16: RPM 800 … 7000 (o último ponto passa a ``max_rpm`` quando maior) e MAP
20 … 260 kPa (o último ponto passa a 300 kPa no clássico). A afinação posterior altera o
arquivo de dados, que é a fonte de verdade; esta fórmula é só o ponto de partida.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from simremap.catalog.contracts import Grid2D

__all__ = ["MAP_AXIS_KPA", "RPM_AXIS", "VE_PARAMS", "VeParams", "rpm_axis", "ve_grid", "ve_value"]

RPM_AXIS: Final[tuple[float, ...]] = (
    800.0, 1000.0, 1250.0, 1500.0, 1750.0, 2000.0, 2500.0, 3000.0,
    3500.0, 4000.0, 4500.0, 5000.0, 5500.0, 6000.0, 6500.0, 7000.0,
)  # fmt: skip
MAP_AXIS_KPA: Final[tuple[float, ...]] = (
    20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0,
    100.0, 120.0, 140.0, 160.0, 180.0, 200.0, 230.0, 260.0,
)  # fmt: skip
VE_MIN: Final = 0.20
VE_MAX: Final = 1.35


@dataclass(frozen=True, slots=True)
class VeParams:
    ve_pk: float
    rpm_pk: float  # rev/min
    rpm_span: float  # rev/min
    k_r: float
    k_m: float
    map_c_kpa: float  # kPa
    map_last_kpa: float = 260.0  # kPa (último ponto do eixo MAP)
    rpm_floor: float = 0.0  # rev/min: abaixo dela o termo em RPM fica constante (0 = desligado)
    rpm_span_high: float = 0.0  # rev/min: vão do ramo acima de rpm_pk (0 = igual a rpm_span)


VE_PARAMS: Final[dict[str, VeParams]] = {
    # hatch (gain-calibration): ramo alto com vão de 6000 rpm (VE 0,94 a 6000 rpm em vez de
    # 0,90): o 2.0 TSI de 3.ª geração respira bem em alta (VVT de admissão e escape); a série
    # fica limitada pela pressão alvo da ECU (que cai acima de 5000 rpm), não pela VE.
    "hatch-20t-gdi": VeParams(0.98, 4200.0, 4000.0, 0.35, 0.30, 60.0, rpm_span_high=6000.0),
    "coupe-30t-i6": VeParams(1.00, 4500.0, 4500.0, 0.30, 0.30, 60.0),
    # classic e muscle afinados contra o Reference Benchmark Baseline v1 (T404, T405).
    "classic-20t-swap": VeParams(0.95, 5500.0, 4500.0, 0.35, 0.25, 70.0, map_last_kpa=300.0),
    "muscle-v8-sc": VeParams(0.96, 5600.0, 4500.0, 0.80, 0.30, 60.0, rpm_floor=2000.0),
}


def ve_value(params: VeParams, rpm: float, map_kpa: float) -> float:
    rpm_eff = max(rpm, params.rpm_floor)
    high = params.rpm_span_high > 0.0 and rpm_eff > params.rpm_pk
    span = params.rpm_span_high if high else params.rpm_span
    rpm_term = 1.0 - params.k_r * ((rpm_eff - params.rpm_pk) / span) ** 2
    map_term = 1.0 - params.k_m * math.exp(-map_kpa / params.map_c_kpa)
    return min(max(params.ve_pk * rpm_term * map_term, VE_MIN), VE_MAX)


def rpm_axis(max_rpm: float) -> list[float]:
    axis = list(RPM_AXIS)
    if max_rpm > axis[-1]:
        axis[-1] = float(max_rpm)
    return axis


def ve_grid(vehicle_id: str, max_rpm: float, decimals: int = 4) -> Grid2D:
    """Grelha ``true_ve`` 16 × 16 (x = rpm, y = map_kpa) do veículo."""
    params = VE_PARAMS[vehicle_id]
    xs = rpm_axis(max_rpm)
    ys = list(MAP_AXIS_KPA)
    ys[-1] = params.map_last_kpa
    z = [[round(ve_value(params, x, y), decimals) for x in xs] for y in ys]
    return Grid2D(x_name="rpm", x_values=xs, y_name="map_kpa", y_values=ys, z_values=z)
