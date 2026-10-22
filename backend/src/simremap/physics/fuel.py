"""Ar aprisionado, injeção, wall-wetting tau-X e lambda (Apêndices A.2 e A.3; RF-05 a RF-08, RF-16).

A VE física ``VE_true`` vem do catálogo (``EngineSpec.true_ve``) e nunca é vista pela ECU.

Cruzamento de válvulas (002 RF-10, D-05): ``ValveOverlap`` corrige a VE e a massa
residual pelo overlap ``overlap_base + vvt_in − vvt_ex``, sempre RELATIVO ao overlap de
série da rotação (comandos de came do ``reference_command_schedule``, o mesmo operando
do benchmark v1). Na posição de série o efeito líquido é exatamente nulo. Sinais (iguais
aos de ``PhysicsEngine._events``): ``vvt_in`` > 0 adianta a admissão (abre mais cedo e
aumenta o overlap); ``vvt_ex`` > 0 adianta o escape (fecha mais cedo e reduz o overlap).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass

from simremap.catalog.contracts import EngineSpec, FuelSpec, InjectorSpec, VehicleSpec
from simremap.physics.interp import Interp2D

__all__ = [
    "CP_MIX_J_KG_K",
    "GAMMA_AIR",
    "R_AIR",
    "T_RESIDUAL_K",
    "InjectorModel",
    "TrueVolumetricEfficiency",
    "ValveOverlap",
    "WallFilm",
    "collector_lambda",
    "evaporative_cooling_k",
    "lambda_of",
    "residual_fraction",
    "trapped_air_kg",
]

R_AIR = 287.05  # J/(kg·K)
GAMMA_AIR = 1.40
T_RESIDUAL_K = 1000.0  # T_res (A.5)
CP_MIX_J_KG_K = 1100.0  # c_p,mix (A.3)
VE_MIN, VE_MAX = 0.20, 1.35
XR_MAX = 0.40
# Cruzamento de válvulas (inferido, D-05; calibrado para efeito nulo na posição de série).
OVERLAP_BASE_FRACTION = 0.25  # overlap_base = 0,25 · (IVC_abdc + EVO_bbdc), °
OVERLAP_SCALE_DEG = 40.0  # escala do tanh(overlap / 40°)
K_OVERLAP_VE = 0.08  # ganho máximo da VE pelo overlap
K_OVERLAP_RESIDUAL = 0.5  # ganho da massa residual pelo overlap
OVERLAP_RPM_CROSS = 3500.0  # rev/min: troca de diluição (baixa) para lavagem (alta)
OVERLAP_RPM_WIDTH = 1000.0  # rev/min: largura da transição
SCAVENGE_DP_KPA = 20.0  # kPa: escala de p_man − p_exh na lavagem
RESIDUAL_SCALE_MIN = 0.2


class ValveOverlap:
    """Efeito do cruzamento de válvulas na VE e na massa residual (custo O(1)).

    ``d = tanh(ov / 40) − tanh(ov_ref(rpm) / 40)`` com ``ov = overlap_base + vvt_in − vvt_ex``
    (``vvt_ex`` > 0 adianta o came de escape e fecha o escape mais cedo) e ``ov_ref``
    interpolado dos comandos de came de série. O sinal
    ``s = −(1 − b) + b · tanh((p_man − p_exh) / 20 kPa)``, com
    ``b = (1 + tanh((rpm − 3500) / 1000)) / 2``, é negativo em baixa rotação (diluição) e
    positivo em alta rotação com ``p_man > p_exh`` (lavagem). VE ``× (1 + 0,08 · d · s)``;
    massa residual ``× max(0,2; 1 − 0,5 · d · s)``.
    """

    __slots__ = ("_ref_overlap", "_ref_rpm", "base_deg")

    def __init__(self, engine: EngineSpec, reference: list[tuple[float, float, float]]) -> None:
        self.base_deg = OVERLAP_BASE_FRACTION * (engine.ivc_deg_abdc + engine.evo_deg_bbdc)
        points = sorted(reference) or [(0.0, 0.0, 0.0)]
        self._ref_rpm = [p[0] for p in points]
        self._ref_overlap = [self.overlap_deg(p[1], p[2]) for p in points]

    @classmethod
    def from_vehicle(cls, vehicle: VehicleSpec) -> ValveOverlap:
        """Overlap de série a partir do ``reference_command_schedule`` do veículo."""
        points = vehicle.reference_command_schedule.points
        return cls(vehicle.engine, [(p.rpm, p.vvt_intake_deg, p.vvt_exhaust_deg) for p in points])

    def overlap_deg(self, vvt_in_deg: float, vvt_ex_deg: float) -> float:
        """Overlap em °: admissão adiantada aumenta, escape adiantado reduz."""
        return self.base_deg + vvt_in_deg - vvt_ex_deg

    def reference_deg(self, rpm: float) -> float:
        """Overlap de série na rotação (interpolação linear, bordas constantes)."""
        xs = self._ref_rpm
        ys = self._ref_overlap
        i = bisect_right(xs, rpm)
        if i <= 0:
            return ys[0]
        if i >= len(xs):
            return ys[-1]
        x0, x1 = xs[i - 1], xs[i]
        return ys[i - 1] + (ys[i] - ys[i - 1]) * (rpm - x0) / (x1 - x0)

    def delta(self, rpm: float, vvt_in_deg: float, vvt_ex_deg: float) -> float:
        """``d``: diferença de ``tanh(ov/40)`` face à posição de série (0 em série)."""
        ov = self.overlap_deg(vvt_in_deg, vvt_ex_deg)
        ref = self.reference_deg(rpm)
        if ov == ref:
            return 0.0
        return math.tanh(ov / OVERLAP_SCALE_DEG) - math.tanh(ref / OVERLAP_SCALE_DEG)

    @staticmethod
    def sign(rpm: float, p_man_kpa: float, p_exh_kpa: float) -> float:
        """``s`` em [−1, 1]: diluição em baixa rotação, lavagem em alta com p_man > p_exh."""
        blend = 0.5 * (1.0 + math.tanh((rpm - OVERLAP_RPM_CROSS) / OVERLAP_RPM_WIDTH))
        scavenge = math.tanh((p_man_kpa - p_exh_kpa) / SCAVENGE_DP_KPA)
        return -(1.0 - blend) + blend * scavenge

    def ve_factor(self, d: float, rpm: float, p_man_kpa: float, p_exh_kpa: float) -> float:
        if d == 0.0:
            return 1.0
        return 1.0 + K_OVERLAP_VE * d * self.sign(rpm, p_man_kpa, p_exh_kpa)

    def residual_factor(self, d: float, rpm: float, p_man_kpa: float, p_exh_kpa: float) -> float:
        if d == 0.0:
            return 1.0
        s = self.sign(rpm, p_man_kpa, p_exh_kpa)
        return max(RESIDUAL_SCALE_MIN, 1.0 - K_OVERLAP_RESIDUAL * d * s)


class TrueVolumetricEfficiency:
    """VE física (A.2).

    ``VE_true = VE_map(rpm, map) · (1 + k_vvt · g_vvt) · f_ov · (r_c − (p_exh/p_man)^(1/γ)) /
    (r_c − 1)``, com ``f_ov`` do ``ValveOverlap`` (1 sem overlap ou na posição de série).
    """

    __slots__ = ("_g_vvt", "_k_vvt", "_map", "_rc", "overlap")

    def __init__(self, engine: EngineSpec, overlap: ValveOverlap | None = None) -> None:
        self._map = Interp2D.from_grid(engine.true_ve)
        self._rc = engine.compression_ratio
        self.overlap = overlap
        if engine.vvt is not None:
            self._k_vvt = engine.vvt.k_vvt
            self._g_vvt: Interp2D | None = Interp2D.from_grid(engine.vvt.g_vvt)
        else:
            self._k_vvt = 0.0
            self._g_vvt = None

    def map_value(self, rpm: float, map_kpa: float) -> float:
        return self._map(rpm, map_kpa)

    def overlap_delta(self, rpm: float, vvt_in_deg: float, vvt_ex_deg: float) -> float:
        """``d`` do ``ValveOverlap`` (0 sem modelo de overlap)."""
        if self.overlap is None:
            return 0.0
        return self.overlap.delta(rpm, vvt_in_deg, vvt_ex_deg)

    def __call__(
        self,
        rpm: float,
        map_kpa: float,
        p_exh_kpa: float,
        vvt_deg: float,
        vvt_ex_deg: float = 0.0,
    ) -> float:
        ve = self._map(rpm, map_kpa)
        if self._g_vvt is not None:
            ve *= 1.0 + self._k_vvt * self._g_vvt(rpm, vvt_deg)
        if self.overlap is not None:
            d = self.overlap.delta(rpm, vvt_deg, vvt_ex_deg)
            ve *= self.overlap.ve_factor(d, rpm, map_kpa, p_exh_kpa)
        ratio = max(p_exh_kpa, 1.0) / max(map_kpa, 1.0)
        rc = self._rc
        ve *= (rc - ratio ** (1.0 / GAMMA_AIR)) / (rc - 1.0)
        return float(min(max(ve, VE_MIN), VE_MAX))


def trapped_air_kg(ve: float, map_kpa: float, t_man_k: float, vd_cyl_m3: float) -> float:
    """``m_air = VE_true · ρ_man · V_d,cyl`` com ``ρ_man = 1000·p/(R·T)``."""
    return ve * 1000.0 * map_kpa / (R_AIR * t_man_k) * vd_cyl_m3


def residual_fraction(
    p_exh_kpa: float,
    vc_m3: float,
    m_air_kg: float,
    m_fuel_kg: float,
    overlap_scale: float = 1.0,
) -> tuple[float, float]:
    """Massa residual ``m_res = p_exh · V_c / (R · T_res) · f_ov`` e a fração ``x_r`` (saturada).

    ``overlap_scale`` é o ``ValveOverlap.residual_factor`` (1 na posição de série).
    """
    m_res = 1000.0 * p_exh_kpa * vc_m3 / (R_AIR * T_RESIDUAL_K) * overlap_scale
    total = m_res + m_air_kg + m_fuel_kg
    x_r = m_res / total if total > 0.0 else 0.0
    return m_res, min(x_r, XR_MAX)


def evaporative_cooling_k(
    m_fuel_kg: float, m_air_kg: float, h_fg_kj_kg: float, direct_injection: bool
) -> float:
    """``ΔT_evap = f_evap · m_fuel · h_fg / ((m_air + m_fuel) · c_p,mix)`` (K)."""
    total = m_air_kg + m_fuel_kg
    if total <= 0.0 or m_fuel_kg <= 0.0:
        return 0.0
    f_evap = 1.0 if direct_injection else 0.5
    return f_evap * m_fuel_kg * h_fg_kj_kg * 1000.0 / (total * CP_MIX_J_KG_K)


def lambda_of(m_air_kg: float, m_fuel_kg: float, afr_stoich: float) -> float | None:
    """``λ = m_air / (m_fuel · AFR_st)``; ``None`` sem combustível (λ = +∞)."""
    if m_fuel_kg <= 0.0:
        return None
    return m_air_kg / (m_fuel_kg * afr_stoich)


def collector_lambda(
    m_air_kg: list[float], m_fuel_kg: list[float], afr_stoich: float
) -> float | None:
    """``λ_col = Σ m_air / (AFR_st · Σ m_fuel)`` (ponderado por massa)."""
    fuel = math.fsum(m_fuel_kg)
    if fuel <= 0.0:
        return None
    return math.fsum(m_air_kg) / (afr_stoich * fuel)


class InjectorModel:
    """Massa injetada (A.3): vazão estática, √(Δp/Δp_ref) e dead time por tensão e Δp."""

    __slots__ = ("_dead", "density", "flow_m3_s", "min_pulse_ms", "spec")

    def __init__(self, spec: InjectorSpec, fuel: FuelSpec) -> None:
        self.spec = spec
        self._dead = Interp2D.from_grid(spec.dead_time_ms)
        self.flow_m3_s = spec.flow_cc_min * spec.count_per_cyl / 60.0 * 1e-6
        self.density = fuel.density_kg_m3
        self.min_pulse_ms = spec.min_pulse_ms

    def set_fuel(self, fuel: FuelSpec) -> None:
        self.density = fuel.density_kg_m3

    def dead_time_ms(self, battery_v: float, dp_kpa: float) -> float:
        """``t_dead`` interpolado (borda fora da tabela)."""
        return self._dead(battery_v, dp_kpa)

    def mass_kg(
        self, pulse_ms: float, dp_kpa: float, battery_v: float, flow_factor: float = 1.0
    ) -> float:
        """``m_inj = ρ_f · Q · √(Δp/Δp_ref) · max(0, PW − t_dead) / 1000`` (kg)."""
        open_ms = pulse_ms - self.dead_time_ms(battery_v, dp_kpa)
        if open_ms <= 0.0 or dp_kpa <= 0.0:
            return 0.0
        scale = math.sqrt(dp_kpa / self.spec.dp_ref_kpa)
        return self.density * self.flow_m3_s * scale * open_ms / 1000.0 * flow_factor

    def pulse_for_mass_ms(self, mass_kg: float, dp_kpa: float, battery_v: float) -> float:
        """Inverso de ``mass_kg``: pulso (ms) que injeta ``mass_kg`` (para pilotos de teste)."""
        if mass_kg <= 0.0:
            return 0.0
        scale = math.sqrt(max(dp_kpa, 1.0) / self.spec.dp_ref_kpa)
        open_ms = mass_kg * 1000.0 / (self.density * self.flow_m3_s * scale)
        return open_ms + self.dead_time_ms(battery_v, dp_kpa)


@dataclass(slots=True)
class WallFilm:
    """Modelo tau-X de Aquino por cilindro (estado = massa de filme, kg)."""

    enabled: bool
    direct_injection: bool

    def parameters(self, ect_c: float) -> tuple[float, float]:
        """``(X, τ)``: PFI ``X = 0,25·f_T``, ``τ = 0,30 s·f_T``; GDI ``X = 0,02``, ``τ = 0,05 s``.

        ``X`` é saturado em 0,95 (com ``f_T = 4`` a fórmula daria X = 1, filme sem fim).
        """
        if self.direct_injection:
            return 0.02, 0.05
        f_t = min(max(math.exp(0.02 * (90.0 - ect_c)), 1.0), 4.0)
        return min(0.25 * f_t, 0.95), 0.30 * f_t

    def step(
        self, film_kg: float, m_inj_kg: float, dt_event_s: float, ect_c: float
    ) -> tuple[float, float]:
        """Um evento: devolve ``(m_cyl, film_novo)``.

        ``m_evap = film · (1 − e^(−Δt/τ))``; ``m_cyl = (1 − X)·m_inj + m_evap``;
        ``film' = film − m_evap + X·m_inj``.
        """
        if not self.enabled:
            return m_inj_kg, 0.0
        x, tau = self.parameters(ect_c)
        m_evap = film_kg * (1.0 - math.exp(-max(dt_event_s, 0.0) / tau))
        m_cyl = (1.0 - x) * m_inj_kg + m_evap
        return m_cyl, film_kg - m_evap + x * m_inj_kg
