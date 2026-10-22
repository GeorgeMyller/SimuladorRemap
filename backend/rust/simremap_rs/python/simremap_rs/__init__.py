"""Kernels nativos do SimuladorRemap (Rust via PyO3).

O backend importa este pacote de forma opcional: sem a extensão compilada,
os módulos Python usam a implementação de referência em Python puro.
"""

from simremap_rs._native import __version__, cycle, damage, tables

__all__ = ["__version__", "cycle", "damage", "tables"]
