"""Sinal de knock sintético por cilindro para a ECU (RF-05).

``KnockSignal.intensity_i = g_i · I_w,i + b(rpm) · ε_i``:

- ``I_w,i`` é a intensidade do ciclo só se ``θ_k`` cair na janela do sensor
  (``knock_window_start_deg_atdc`` a ``knock_window_end_deg_atdc``);
- ``g_i`` é o ganho do cilindro (0,85 nas pontas, 1,0 nos centrais por padrão);
- ``b(rpm) = 0,05 + 0,10 · (rpm / 7000)²`` é o piso de ruído mecânico;
- ``ε_i`` é lognormal (μ 0, σ ``knock_noise_sigma``) do substream ``knock_noise``.

O valor fica retido até o próximo evento do mesmo cilindro.
"""

from __future__ import annotations

import numpy as np

from simremap.damage.config import DamageConfig
from simremap.physics.contracts import KnockSignal

__all__ = ["KnockSignalGenerator", "in_sensor_window", "noise_floor"]


def noise_floor(rpm: float, config: DamageConfig) -> float:
    """``b(rpm) = 0,05 + 0,10 · (rpm / 7000)²`` (escala de MAPO em bar)."""
    ratio = max(0.0, rpm) / config.knock_noise_floor_rpm_ref
    return config.knock_noise_floor_base + config.knock_noise_floor_slope * ratio * ratio


def in_sensor_window(theta_onset_deg_atdc: float | None, config: DamageConfig) -> bool:
    """Indica se ``θ_k`` está dentro da janela de leitura do sensor."""
    if theta_onset_deg_atdc is None:
        return False
    return (
        config.knock_window_start_deg_atdc
        <= theta_onset_deg_atdc
        <= config.knock_window_end_deg_atdc
    )


class KnockSignalGenerator:
    """Mantém o último valor do sinal por cilindro."""

    __slots__ = ("_config", "_gains", "_rng", "_values")

    def __init__(self, n_cyl: int, config: DamageConfig, rng: np.random.Generator) -> None:
        self._config = config
        self._gains = config.sensor_gains(n_cyl)
        self._rng = rng
        self._values = [0.0] * n_cyl

    @property
    def values(self) -> list[float]:
        return list(self._values)

    def on_cycle(
        self, cylinder: int, intensity: float, theta_onset_deg_atdc: float | None, rpm: float
    ) -> float:
        """Atualiza o sinal do cilindro (1..n) com o ciclo atual e devolve o valor."""
        epsilon = float(self._rng.lognormal(0.0, self._config.knock_noise_sigma))
        windowed = intensity if in_sensor_window(theta_onset_deg_atdc, self._config) else 0.0
        value = self._gains[cylinder - 1] * windowed + noise_floor(rpm, self._config) * epsilon
        self._values[cylinder - 1] = value
        return value

    def signal(self) -> KnockSignal:
        """``KnockSignal`` do último ciclo de cada cilindro."""
        return KnockSignal.model_construct(intensity=list(self._values))

    def reset(self) -> None:
        """Zera o sinal (restauração do motor)."""
        self._values = [0.0] * len(self._values)

    def load(self, values: list[float]) -> None:
        """Repõe valores de um snapshot."""
        if len(values) != len(self._values):
            raise ValueError("sinal com número de cilindros diferente")
        self._values = [float(v) for v in values]
