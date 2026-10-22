"""Espectro de knock e traço de pressão por frame (tel RF-20, RF-21; D-BUS-10; D-WS-08).

O gerador do espectro é único e vive no dano (``DamageModel.spectrum_frame``, substream
``spectrum``): este módulo só o consome e converte para ``KnockSpectrum`` (256 bins de 0 a
20 kHz, magnitude em dB com 1 casa, 4 ressonâncias de Draper). Valores não finitos viram o
piso de -200 dB (o contrato exige 256 números).

O traço de pressão vem do último ``CombustionEvent`` de cada cilindro (``pressure_kpa``, 1
ponto por grau desde a faísca); sai a no máximo 10 Hz.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any, Final, Protocol

import numpy as np

from simremap.telemetry.contracts import (
    RESONANCE_MODES,
    SPECTRUM_BINS,
    KnockSpectrum,
    PressureTrace,
)

__all__ = [
    "DB_FLOOR",
    "TRACE_MAX_HZ",
    "SpectrumFrameLike",
    "SpectrumSource",
    "spectrum_payload",
    "to_knock_spectrum",
    "trace_every_n_frames",
    "trace_payload",
    "trace_to_contract",
]

DB_FLOOR: Final = -200.0
TRACE_MAX_HZ: Final = 10


class SpectrumFrameLike(Protocol):
    """Parte de ``damage.spectrum.KnockSpectrumFrame`` usada aqui."""

    @property
    def bins_hz(self) -> list[float]: ...

    @property
    def magnitude_db(self) -> list[float]: ...

    @property
    def resonance_hz(self) -> list[float]: ...


SpectrumSource = Callable[[float], SpectrumFrameLike]
"""``DamageModel.spectrum_frame(t_sim_s)`` (ou equivalente)."""


def spectrum_payload(frame: SpectrumFrameLike) -> dict[str, Any]:
    """Dicionário ``KnockSpectrum`` serializável (dB com 1 casa), sem validação Pydantic."""
    mags = np.asarray(frame.magnitude_db, dtype=np.float64)
    bins = frame.bins_hz
    res = frame.resonance_hz
    if len(bins) != SPECTRUM_BINS or mags.size != SPECTRUM_BINS:
        raise ValueError(f"espectro deve ter {SPECTRUM_BINS} bins")
    if len(res) != RESONANCE_MODES:
        raise ValueError(f"espectro deve ter {RESONANCE_MODES} ressonâncias")
    mags = np.where(np.isfinite(mags), np.maximum(mags, DB_FLOOR), DB_FLOOR)
    return {
        "bins_hz": bins if isinstance(bins, list) else [float(b) for b in bins],
        "magnitude_db": np.round(mags, 1).tolist(),
        "resonance_hz": np.round(np.asarray(res, dtype=np.float64), 1).tolist(),
        "sensor": "block",
    }


def to_knock_spectrum(frame: SpectrumFrameLike) -> KnockSpectrum:
    """``KnockSpectrumFrame`` do dano → ``KnockSpectrum`` do contrato WS."""
    return KnockSpectrum.model_validate(spectrum_payload(frame))


def trace_every_n_frames(fps: int) -> int:
    """De quantos em quantos frames sai o traço (≤ 10 Hz)."""
    return max(1, math.ceil(fps / TRACE_MAX_HZ))


def trace_payload(theta_start_deg: float, pressure_kpa: Sequence[float]) -> dict[str, list[Any]]:
    """``crank_deg`` (inteiros ATDC, 1 por grau) e ``p_bar`` (absoluta, 2 casas)."""
    start = math.floor(theta_start_deg)
    p = np.asarray(pressure_kpa, dtype=np.float64) / 100.0
    p = np.where(np.isfinite(p), p, 0.0)
    return {"crank_deg": list(range(start, start + p.size)), "p_bar": np.round(p, 2).tolist()}


def trace_to_contract(cylinder: int, trace: dict[str, list[Any]]) -> PressureTrace:
    return PressureTrace(cylinder=cylinder, crank_deg=trace["crank_deg"], p_bar=trace["p_bar"])
