"""Lista de bloqueio de marcas em textos exibidos (vehicle-catalog RF-07, Apêndice A.6; D-34).

A comparação é por palavra inteira e sem distinção de maiúsculas nem de acentos: o texto
é normalizado (NFKD, sem diacríticos, minúsculas) e um termo só casa quando não tem letra
nem dígito colado antes ou depois (``"Hatch EA888"`` casa ``ea888``; ``"clássico"`` não
casa ``ls``). Os nomes canónicos dos perfis (``FT-Pro``, ``M1-Race``...) ficam fora do
âmbito: o teste cobre só textos de veículos e combustíveis.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

__all__ = ["BLOCKED_TERMS", "find_trademarks", "normalize_text"]

BLOCKED_TERMS: Final[tuple[str, ...]] = (
    # Fabricantes e marcas
    "volkswagen", "vw", "audi", "seat", "skoda", "bmw", "toyota", "lexus", "ford",
    "mustang", "chevrolet", "gm", "corvette", "camaro", "dodge", "mopar", "bosch",
    "continental", "fueltech", "motec", "haltech", "garrett", "borgwarner", "ihi",
    "eaton", "whipple", "magnuson", "roush", "shelby",
    # Códigos de motor e de peça
    "ea888", "tsi", "tfsi", "gti", "b58", "n55", "2jz", "2jz-gte", "supra", "coyote",
    "ls", "ls3", "lsa", "lt4", "ap", "is20", "is38", "ft600", "ft550", "m1", "elite",
    "nexus",
)  # fmt: skip


def normalize_text(text: str) -> str:
    """Minúsculas, sem diacríticos (NFKD) e com espaços simples."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.casefold().split())


_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (term, re.compile(rf"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])")) for term in BLOCKED_TERMS
)


def find_trademarks(text: str, terms: Iterable[str] | None = None) -> list[str]:
    """Termos da lista encontrados em ``text`` (ordem da lista, sem repetição)."""
    normalized = normalize_text(text)
    allowed = None if terms is None else {normalize_text(t) for t in terms}
    return [
        term
        for term, pattern in _PATTERNS
        if (allowed is None or term in allowed) and pattern.search(normalized)
    ]
