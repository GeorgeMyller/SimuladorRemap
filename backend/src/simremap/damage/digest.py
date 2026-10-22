"""Substreams semeados e ``damage_digest`` canônico (RF-32; D-BUS-02).

Árvore de substreams do dano: ``SeedSequence(seed, spawn_key=(1,)).spawn(5)`` em ordem
fixa ``preignition``, ``lspi``, ``knock_noise``, ``rod_weights``, ``spectrum``, todos com
``Generator(PCG64(...))``. O estado do substream ``spectrum`` fica fora do digest, para
que a taxa de frames da UI não o altere.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.random import PCG64, Generator, SeedSequence

__all__ = [
    "DAMAGE_SPAWN_KEY",
    "SUBSTREAM_NAMES",
    "DamageStreams",
    "canonical_digest",
    "damage_streams",
]

DAMAGE_SPAWN_KEY: Final = (1,)
SUBSTREAM_NAMES: Final = ("preignition", "lspi", "knock_noise", "rod_weights", "spectrum")


@dataclass(frozen=True, slots=True)
class DamageStreams:
    preignition: Generator
    lspi: Generator
    knock_noise: Generator
    rod_weights: Generator
    spectrum: Generator

    def digest_states(self) -> dict[str, Any]:
        """Estados dos geradores que entram no digest (sem ``spectrum``)."""
        return {
            "preignition": self.preignition.bit_generator.state,
            "lspi": self.lspi.bit_generator.state,
            "knock_noise": self.knock_noise.bit_generator.state,
            "rod_weights": self.rod_weights.bit_generator.state,
        }

    def all_states(self) -> dict[str, Any]:
        return {**self.digest_states(), "spectrum": self.spectrum.bit_generator.state}

    def load_states(self, states: dict[str, Any]) -> None:
        for name in SUBSTREAM_NAMES:
            getattr(self, name).bit_generator.state = states[name]


def damage_streams(seed: int) -> DamageStreams:
    """Cria os 5 substreams do dano a partir da ``seed`` da sessão."""
    children = SeedSequence(seed, spawn_key=DAMAGE_SPAWN_KEY).spawn(len(SUBSTREAM_NAMES))
    gens = [Generator(PCG64(child)) for child in children]
    return DamageStreams(*gens)


def canonical_digest(scalars: dict[str, Any], arrays: dict[str, np.ndarray]) -> str:
    """SHA-256 hex de ``scalars`` (JSON ordenado) + arrays float64 little-endian por nome."""
    h = hashlib.sha256()
    h.update(json.dumps(scalars, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    for name in sorted(arrays):
        h.update(name.encode("utf-8"))
        h.update(np.ascontiguousarray(arrays[name], dtype="<f8").tobytes())
    return h.hexdigest()
