"""Geometria do cilindro (Apêndice A.1) e calendário de eventos por IVC (RF-02).

Convenção angular: θ em graus de cambota, 0 = PMS de compressão do cilindro 1, ciclo de
720°. O ângulo local de um cilindro vai de −360° a +360° em torno do seu PMS de compressão.
As tabelas ``V(θ)``, ``dV/dθ`` e ``A_w(θ)`` são pré-calculadas a cada 1° (721 pontos) com
NumPy e guardadas como listas Python para o laço do solver.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from simremap.catalog.contracts import EngineSpec

__all__ = [
    "CYCLE_DEG",
    "CrankSchedule",
    "CylinderGeometry",
    "crank_advance_deg",
    "mean_piston_speed",
]

CYCLE_DEG = 720.0
F_CROWN = 1.1  # fator de área da coroa do pistão e da cabeça (A.1)
DEG_OFFSET = 360  # índice da tabela = θ_local + 360


def crank_advance_deg(rpm: float, dt: float) -> float:
    """Avanço angular por tick ``Δθ = 6 · rpm · dt`` (graus)."""
    return 6.0 * rpm * dt


def mean_piston_speed(stroke_m: float, rpm: float) -> float:
    """Velocidade média do pistão ``S̄p = 2 · S · rpm / 60`` (m/s)."""
    return 2.0 * stroke_m * rpm / 60.0


@dataclass(frozen=True, slots=True)
class CylinderGeometry:
    """Geometria de um cilindro e tabelas angulares a 1°."""

    bore_m: float
    stroke_m: float
    crank_radius_m: float
    rod_m: float
    compression_ratio: float
    piston_area_m2: float
    vd_cyl_m3: float  # cilindrada unitária
    vd_total_m3: float
    vc_m3: float  # volume da câmara (folga)
    volume_m3: list[float]  # V(θ), índice θ + 360
    dvol_m3_per_deg: list[float]  # dV/dθ por grau
    wall_area_m2: list[float]  # A_w(θ)

    @classmethod
    def from_engine(cls, engine: EngineSpec) -> CylinderGeometry:
        bore = engine.bore_mm / 1000.0
        stroke = engine.stroke_mm / 1000.0
        a = stroke / 2.0
        rod = engine.rod_length_mm / 1000.0
        rc = engine.compression_ratio
        ap = math.pi / 4.0 * bore * bore
        vd = ap * stroke
        vc = vd / (rc - 1.0)
        theta = np.radians(np.arange(-DEG_OFFSET, DEG_OFFSET + 1, dtype=np.float64))
        sin_t = np.sin(theta)
        cos_t = np.cos(theta)
        root = np.sqrt(rod * rod - (a * sin_t) ** 2)
        vol = vc + ap * (rod + a - a * cos_t - root)
        dvol_rad = ap * a * sin_t * (1.0 + a * cos_t / root)
        dvol_deg = dvol_rad * (math.pi / 180.0)
        # A_w = 2·A_p·f_crown + π·B·(V − V_c)/A_p + A_c, com A_c = π·B·V_c/A_p.
        wall = 2.0 * ap * F_CROWN + math.pi * bore * vol / ap
        return cls(
            bore_m=bore,
            stroke_m=stroke,
            crank_radius_m=a,
            rod_m=rod,
            compression_ratio=rc,
            piston_area_m2=ap,
            vd_cyl_m3=vd,
            vd_total_m3=vd * engine.n_cyl,
            vc_m3=vc,
            volume_m3=[float(v) for v in vol],
            dvol_m3_per_deg=[float(v) for v in dvol_deg],
            wall_area_m2=[float(v) for v in wall],
        )

    def volume_at(self, theta_deg: float) -> float:
        """``V(θ)`` analítico para ângulo arbitrário (graus, local)."""
        t = math.radians(theta_deg)
        a = self.crank_radius_m
        root = math.sqrt(self.rod_m**2 - (a * math.sin(t)) ** 2)
        return self.vc_m3 + self.piston_area_m2 * (self.rod_m + a - a * math.cos(t) - root)

    def dvolume_at(self, theta_deg: float) -> float:
        """``dV/dθ`` analítico (m³/rad)."""
        t = math.radians(theta_deg)
        a = self.crank_radius_m
        root = math.sqrt(self.rod_m**2 - (a * math.sin(t)) ** 2)
        return self.piston_area_m2 * a * math.sin(t) * (1.0 + a * math.cos(t) / root)


@dataclass(frozen=True, slots=True)
class CrankSchedule:
    """Fase de cada cilindro (PMS de compressão no ciclo de 720°) pela ordem de ignição."""

    n_cyl: int
    firing_order: tuple[int, ...]
    tdc_phase_deg: tuple[float, ...]  # índice 0 = cilindro 1

    @classmethod
    def from_engine(cls, engine: EngineSpec) -> CrankSchedule:
        n = engine.n_cyl
        phases = [0.0] * n
        for position, cyl in enumerate(engine.firing_order):
            phases[cyl - 1] = CYCLE_DEG * position / n
        return cls(n_cyl=n, firing_order=tuple(engine.firing_order), tdc_phase_deg=tuple(phases))

    def local_angle(self, theta_deg: float, cyl_index: int) -> float:
        """Ângulo local do cilindro em [−360, 360)."""
        loc = (theta_deg - self.tdc_phase_deg[cyl_index]) % CYCLE_DEG
        return loc - CYCLE_DEG if loc >= CYCLE_DEG / 2 else loc

    def crossings(
        self, theta_old: float, delta_deg: float, local_event_deg: float
    ) -> list[tuple[float, int]]:
        """Cilindros cujo ângulo local ``local_event_deg`` cai em ``(θ_old, θ_old + Δθ]``.

        Devolve pares ``(offset_deg, cyl_index)`` ordenados por ângulo (ordem de ignição).
        ``Δθ`` < 720° (garantido por ``rpm ≤ 10 000`` e ``sim_hz ≥ 100``).
        """
        if delta_deg <= 0.0:
            return []
        out: list[tuple[float, int]] = []
        for idx in range(self.n_cyl):
            event_global = (self.tdc_phase_deg[idx] + local_event_deg) % CYCLE_DEG
            offset = (event_global - theta_old) % CYCLE_DEG
            if offset == 0.0:
                offset = CYCLE_DEG  # o próprio θ_old já foi tratado no tick anterior
            if offset <= delta_deg:
                out.append((offset, idx))
        out.sort()
        return out
