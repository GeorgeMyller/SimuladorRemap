"""Sensores: ruído gaussiano semeado por canal, atrasos de 1.ª ordem e knock (A.10; RF-17, RF-26).

Árvore de sementes (D-BUS-02): ``SeedSequence(seed, spawn_key=(0,)).spawn(8)`` na ordem
fixa ``map, iat, ect, lambda, egt, rpm, tps, knock``; cada filho alimenta um
``Generator(PCG64)``. Nada de ``numpy.random`` global (D-07).
"""

from __future__ import annotations

import json
import math
from typing import Final

import numpy as np
from numpy.random import PCG64, Generator, SeedSequence

__all__ = [
    "KNOCK_BASE_V",
    "KNOCK_GAIN_V",
    "KNOCK_MAX_V",
    "KNOCK_SIGMA_V",
    "LAMBDA_MAX",
    "LAMBDA_MIN",
    "NOISE_CHANNELS",
    "PHYSICS_SPAWN_KEY",
    "SensorNoise",
    "clamp_lambda",
    "knock_block",
    "knock_index",
    "knock_voltage",
    "wideband_delay_s",
    "wideband_update",
]

PHYSICS_SPAWN_KEY: Final = (0,)
NOISE_CHANNELS: Final[tuple[str, ...]] = (
    "map",
    "iat",
    "ect",
    "lambda",
    "egt",
    "rpm",
    "tps",
    "knock",
)
KNOCK_BASE_V = 0.05
KNOCK_GAIN_V = 1.5
KNOCK_MAX_V = 5.0
KNOCK_SIGMA_V = 0.02
LAMBDA_MIN, LAMBDA_MAX = 0.5, 2.0
WIDEBAND_BASE_DELAY_S = 0.02


def wideband_delay_s(rpm: float) -> float:
    """Atraso de transporte ``t_tr = 0,02 s + 2 · 60 / rpm`` (rpm saturado em ≥ 300)."""
    return WIDEBAND_BASE_DELAY_S + 120.0 / max(rpm, 300.0)


def knock_voltage(intensity: float, noise_v: float) -> float:
    """``knock_sensor_v = clip(0,05 V + 1,5 V · intensity + ruído, 0, 5 V)``."""
    v = KNOCK_BASE_V + KNOCK_GAIN_V * intensity + noise_v
    if v < 0.0:
        return 0.0
    return min(v, KNOCK_MAX_V)


def knock_index(voltage: float) -> float:
    """``knock_intensity = clip((V − 0,05) / (5,0 − 0,05), 0, 1)``."""
    idx = (voltage - KNOCK_BASE_V) / (KNOCK_MAX_V - KNOCK_BASE_V)
    if idx < 0.0:
        return 0.0
    return min(idx, 1.0)


class SensorNoise:
    """Um ``Generator(PCG64)`` por canal, com estado serializável (snapshot/digest)."""

    def __init__(self, seed: int) -> None:
        children = SeedSequence(seed, spawn_key=PHYSICS_SPAWN_KEY).spawn(len(NOISE_CHANNELS))
        self.generators: dict[str, Generator] = {
            name: Generator(PCG64(child))
            for name, child in zip(NOISE_CHANNELS, children, strict=True)
        }

    def normal(self, channel: str, sigma: float) -> float:
        """Uma amostra ``N(0, σ)`` do canal (σ = 0 consome a amostra na mesma ordem)."""
        return float(self.generators[channel].standard_normal()) * sigma

    def normals(self, channel: str, sigma: float, n: int) -> list[float]:
        draws: np.ndarray = self.generators[channel].standard_normal(n)
        return [float(v) * sigma for v in draws]

    def state(self) -> dict[str, dict[str, object]]:
        """Estado de cada gerador (inteiros grandes como texto, JSON canónico)."""
        out: dict[str, dict[str, object]] = {}
        for name in NOISE_CHANNELS:
            st = self.generators[name].bit_generator.state
            inner = st["state"]
            out[name] = {
                "state": str(inner["state"]),
                "inc": str(inner["inc"]),
                "has_uint32": int(st["has_uint32"]),
                "uinteger": int(st["uinteger"]),
            }
        return out

    def state_bytes(self) -> bytes:
        return json.dumps(self.state(), sort_keys=True, separators=(",", ":")).encode()

    def set_state(self, state: dict[str, dict[str, object]]) -> None:
        for name in NOISE_CHANNELS:
            entry = state[name]
            bit_gen = self.generators[name].bit_generator
            bit_gen.state = {
                "bit_generator": "PCG64",
                "state": {"state": int(str(entry["state"])), "inc": int(str(entry["inc"]))},
                "has_uint32": int(str(entry["has_uint32"])),
                "uinteger": int(str(entry["uinteger"])),
            }


def clamp_lambda(value: float) -> float:
    """Saturação da wideband em [0,5; 2,0]."""
    if math.isnan(value):
        return LAMBDA_MAX
    return min(max(value, LAMBDA_MIN), LAMBDA_MAX)


def wideband_update(
    buffer: list[float],
    index: int,
    filtered: float,
    lambda_real: float,
    rpm: float,
    dt: float,
    sim_hz: int,
    tau_s: float,
) -> tuple[int, float]:
    """Um tick da wideband: fila de atraso de transporte e depois 1.ª ordem com τ.

    Escreve ``lambda_real`` (saturado) na fila circular, lê o valor atrasado de
    ``round(t_tr · sim_hz)`` ticks e devolve ``(novo_índice, novo_filtrado)``.
    """
    size = len(buffer)
    buffer[index] = clamp_lambda(lambda_real)
    delay_ticks = min(round(wideband_delay_s(rpm) * sim_hz), size - 1)
    delayed = buffer[(index - delay_ticks) % size]
    new_filtered = filtered + (1.0 - math.exp(-dt / tau_s)) * (delayed - filtered)
    return (index + 1) % size, new_filtered


def knock_block(intensity: np.ndarray, noise_v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Versão vetorizada de ``knock_voltage``/``knock_index`` (mesmas fórmulas, A.10)."""
    volts = np.clip(KNOCK_BASE_V + KNOCK_GAIN_V * intensity + noise_v, 0.0, KNOCK_MAX_V)
    index = np.clip((volts - KNOCK_BASE_V) / (KNOCK_MAX_V - KNOCK_BASE_V), 0.0, 1.0)
    return volts, index
