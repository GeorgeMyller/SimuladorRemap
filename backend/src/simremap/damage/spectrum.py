"""Espectro sintético de knock (RF-06; D-BUS-10; D-WS-08).

Gerador único do canal ``knock_spectrum``: o ``telemetry-datalogger`` só converte o
frame para ``KnockSpectrum`` (256 bins de 0 a 20 kHz). Fórmulas (Apêndice B.6):

- velocidade do som do gás queimado ``c = sqrt(γ_b · 287 · T_b)`` (m/s);
- ressonâncias de Draper ``f_mn = α_mn · c / (π · B)`` com ``α_10 = 1,841``,
  ``α_20 = 3,054``, ``α_01 = 3,832`` e ``α_30 = 4,201`` (4.º modo, D-WS-08);
- ``S(f) = 10 · log10(N0(f) + Σ_m A_m · I_max · exp(−(f − f_m)² / (2 · 300²)))`` em dB;
- ``N0(f) = b(rpm) · (1 + 2000 / (f + 200)) · ε_f`` com ``ε_f`` lognormal σ 0,2 do
  substream ``spectrum`` (separado: a taxa de frames não altera o ``damage_digest``).
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
from pydantic import Field

from simremap.core.contracts import ContractModel
from simremap.damage.config import DamageConfig
from simremap.damage.signal import noise_floor
from simremap.telemetry.contracts import RESONANCE_MODES, SPECTRUM_BINS, KnockSpectrum

__all__ = [
    "BIN_WIDTH_HZ",
    "DRAPER_MODES",
    "KnockSpectrumFrame",
    "SpectrumGenerator",
    "draper_frequencies_hz",
    "floor_spectrum",
    "speed_of_sound_m_s",
]

GAS_CONSTANT_J_KG_K: Final = 287.0
SPECTRUM_MAX_HZ: Final = 20_000.0
BIN_WIDTH_HZ: Final = SPECTRUM_MAX_HZ / SPECTRUM_BINS  # 78,125 Hz
PEAK_SIGMA_HZ: Final = 300.0
SPECTRUM_NOISE_SIGMA: Final = 0.2
# (nome do modo, α_mn, amplitude A_m)
DRAPER_MODES: Final[tuple[tuple[str, float, float], ...]] = (
    ("1,0", 1.841, 1.0),
    ("2,0", 3.054, 0.4),
    ("0,1", 3.832, 0.25),
    ("3,0", 4.201, 0.15),
)
BINS_HZ: Final[tuple[float, ...]] = tuple(i * BIN_WIDTH_HZ for i in range(SPECTRUM_BINS))


class KnockSpectrumFrame(ContractModel):
    """Um frame do espectro (agregado por máximo entre cilindros)."""

    t_sim_s: float = Field(ge=0.0)  # s
    bins_hz: list[float] = Field(min_length=SPECTRUM_BINS, max_length=SPECTRUM_BINS)  # Hz
    magnitude_db: list[float] = Field(min_length=SPECTRUM_BINS, max_length=SPECTRUM_BINS)
    resonance_hz: list[float] = Field(min_length=RESONANCE_MODES, max_length=RESONANCE_MODES)
    intensity_max: float = Field(ge=0.0)  # bar, maior intensidade dos ciclos do frame
    rpm: float = Field(ge=0.0)  # rev/min

    def to_telemetry(self) -> KnockSpectrum:
        """Converte para o canal ``knock_spectrum`` do ``telemetry.frame`` (dB com 1 casa)."""
        return KnockSpectrum(
            bins_hz=list(self.bins_hz),
            magnitude_db=[round(v, 1) for v in self.magnitude_db],
            resonance_hz=[round(v, 1) for v in self.resonance_hz],
        )


def speed_of_sound_m_s(gamma: float, temp_k: float) -> float:
    """``c = sqrt(γ · 287 · T)`` em m/s."""
    return math.sqrt(gamma * GAS_CONSTANT_J_KG_K * temp_k)


def draper_frequencies_hz(bore_mm: float, gamma: float, temp_k: float) -> list[float]:
    """Frequências de Draper dos 4 modos (Hz)."""
    c = speed_of_sound_m_s(gamma, temp_k)
    bore_m = bore_mm / 1000.0
    return [alpha * c / (math.pi * bore_m) for _, alpha, _ in DRAPER_MODES]


def floor_spectrum(rpm: float, config: DamageConfig) -> np.ndarray:
    """Piso determinístico ``b(rpm) · (1 + 2000 / (f + 200))`` (sem ``ε_f``)."""
    f = np.asarray(BINS_HZ, dtype=np.float64)
    return noise_floor(rpm, config) * (1.0 + 2000.0 / (f + 200.0))


class SpectrumGenerator:
    """Acumula a maior intensidade entre frames e gera o espectro com ruído semeado."""

    __slots__ = ("_bins", "_config", "_i_max", "_resonances", "_rng")

    def __init__(self, bore_mm: float, config: DamageConfig, rng: np.random.Generator) -> None:
        self._config = config
        self._rng = rng
        self._bins = np.asarray(BINS_HZ, dtype=np.float64)
        self._resonances = draper_frequencies_hz(
            bore_mm, config.burned_gas_gamma, config.burned_gas_temp_k
        )
        self._i_max = 0.0

    @property
    def resonances_hz(self) -> list[float]:
        return list(self._resonances)

    @property
    def i_max(self) -> float:
        """Maior intensidade acumulada desde o último frame (bar)."""
        return self._i_max

    def observe(self, intensity: float) -> None:
        """Regista a intensidade de um ciclo (máximo entre cilindros até o próximo frame)."""
        self._i_max = max(self._i_max, intensity)

    def reset(self) -> None:
        self._i_max = 0.0

    def frame(self, t_sim_s: float, rpm: float) -> KnockSpectrumFrame:
        """Gera o frame atual e zera o acumulador de intensidade."""
        epsilon = self._rng.lognormal(0.0, SPECTRUM_NOISE_SIGMA, size=SPECTRUM_BINS)
        power = floor_spectrum(rpm, self._config) * epsilon
        i_max = self._i_max
        if i_max > 0.0:
            for (_, _, amplitude), f_m in zip(DRAPER_MODES, self._resonances, strict=True):
                power = power + amplitude * i_max * np.exp(
                    -((self._bins - f_m) ** 2) / (2.0 * PEAK_SIGMA_HZ**2)
                )
        self._i_max = 0.0
        return KnockSpectrumFrame(
            t_sim_s=t_sim_s,
            bins_hz=list(BINS_HZ),
            magnitude_db=(10.0 * np.log10(power)).tolist(),
            resonance_hz=list(self._resonances),
            intensity_max=i_max,
            rpm=max(0.0, rpm),
        )
