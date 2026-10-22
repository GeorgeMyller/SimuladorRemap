"""Seletor da extensão nativa ``simremap_rs`` (feature 003, D-02).

``SIMREMAP_NATIVE`` controla o uso dos kernels em Rust:

- ``auto`` (padrão): usa a extensão se ela importar; senão cai no Python de referência;
- ``off``: nunca usa a extensão;
- ``on``: exige a extensão e falha no import se ela estiver ausente.

O módulo é lido uma vez por processo (cada worker de simulação resolve o seu).
"""

from __future__ import annotations

import importlib
import os
from types import ModuleType
from typing import Literal

NativeMode = Literal["auto", "off", "on"]

_MODES: tuple[NativeMode, ...] = ("auto", "off", "on")


class NativeUnavailableError(RuntimeError):
    """``SIMREMAP_NATIVE=on`` sem a extensão ``simremap_rs`` instalada."""


def native_mode() -> NativeMode:
    raw = os.environ.get("SIMREMAP_NATIVE", "auto").strip().lower()
    for mode in _MODES:
        if raw == mode:
            return mode
    raise ValueError(f"SIMREMAP_NATIVE inválido: {raw!r} (use auto, off ou on)")


def _load() -> ModuleType | None:
    mode = native_mode()
    if mode == "off":
        return None
    try:
        module = importlib.import_module("simremap_rs")
    except ImportError as exc:
        if mode == "on":
            raise NativeUnavailableError(
                "SIMREMAP_NATIVE=on, mas a extensão simremap_rs não está instalada "
                "(rode `make native`)."
            ) from exc
        return None
    return module


_NATIVE: ModuleType | None = _load()


def native() -> ModuleType | None:
    """Módulo ``simremap_rs`` ou ``None`` quando o fallback Python está ativo."""
    return _NATIVE


def native_enabled() -> bool:
    return _NATIVE is not None


def native_version() -> str | None:
    return None if _NATIVE is None else str(_NATIVE.__version__)
