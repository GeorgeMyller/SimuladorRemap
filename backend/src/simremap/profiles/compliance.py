"""Conformidade de marcas do ecu-profiles (Apêndice G; D-34; RNF-05).

Lista de bloqueio sem distinção de maiúsculas, por palavra inteira, sem exceções. O nome
exibido do perfil ``oem-stage`` é "OEM-Stage" e não contém termo da lista. Os textos
são normalizados (NFKD, sem diacríticos, minúsculas, espaços simples) e um termo só
casa quando não há letra nem dígito colado antes ou depois.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any, Final

__all__ = ["BLOCKED_TERMS", "find_blocked_terms", "iter_strings"]

BLOCKED_TERMS: Final[tuple[str, ...]] = (
    "FuelTech",
    "FTManager",
    "FT600",
    "FT550",
    "MoTeC",
    "M1 Tune",
    "Haltech",
    "Nexus",
    "NSP",
    "WinOLS",
    "Bosch",
    "Continental",
    "Motronic",
    "Simos",
    "MED17",
    "MG1",
)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (term, re.compile(rf"(?<![0-9a-z]){re.escape(_normalize(term))}(?![0-9a-z])"))
    for term in BLOCKED_TERMS
)


def find_blocked_terms(text: str) -> list[str]:
    """Termos da lista de bloqueio presentes em ``text`` (ordem da lista)."""
    normalized = _normalize(text)
    return [term for term, pattern in _PATTERNS if pattern.search(normalized)]


def iter_strings(value: Any) -> Iterator[str]:
    """Todas as strings (chaves e valores) de uma estrutura JSON aninhada."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
            yield from iter_strings(item)
    elif isinstance(value, Iterable) and not isinstance(value, bytes):
        for item in value:
            yield from iter_strings(item)
