"""Ponte para os kernels nativos do dano (feature 003, T019).

``KERNELS`` é o submódulo ``simremap_rs._native.damage`` quando a extensão está ativa
(``SIMREMAP_NATIVE`` ``auto``/``on``, ver ``simremap.core.native``) e expõe os kernels
desta trilha; senão ``None`` e o dano usa a referência em Python puro. Os chamadores leem
``native_bridge.KERNELS`` no momento da chamada (o ``DamageModel`` na construção), o que
permite aos testes de paridade alternar Python × Rust no mesmo processo.
"""

from __future__ import annotations

from types import ModuleType
from typing import Final

from simremap.core.native import native

__all__ = ["KERNELS", "REQUIRED", "damage_kernels"]

REQUIRED: Final = ("knock_onset", "traces_finite", "DamageKernel")


def damage_kernels() -> ModuleType | None:
    """Submódulo ``damage`` da extensão, se ativo e completo."""
    module = native()
    damage = None if module is None else getattr(module, "damage", None)
    if not isinstance(damage, ModuleType) or not all(hasattr(damage, n) for n in REQUIRED):
        return None
    return damage


KERNELS: ModuleType | None = damage_kernels()
