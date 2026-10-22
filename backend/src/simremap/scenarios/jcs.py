"""JSON canónico RFC 8785 (JCS) e SHA-256 dos artefactos dos cenários (D-11; file-formats 5, 7.1).

Usado por ``scenario_sha256``, ``evaluation_sha256`` e ``SignedPackage.sha256``.

- Canonicalização pela biblioteca ``rfc8785`` (chaves ordenadas por unidades UTF-16, números
  no formato ECMAScript, sem espaços).
- ``NaN``/``Infinity`` tornam o objeto não canonicalizável: ``NotCanonicalizableError`` com o
  caminho JSON do primeiro valor (``$.payload.runs[0].summary.peak_whp``).
- Inteiros fora do domínio seguro do IEEE-754 (|n| > 2^53 − 1, ex.: ``seed`` até 2^63 − 1)
  não existem em JCS sem perda; ``prepare`` converte-os em texto decimal antes do hash
  (decisão de interpretação: os contratos Pydantic aceitam o texto de volta como ``int``).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Final

import rfc8785

__all__ = [
    "MAX_SAFE_INTEGER",
    "NotCanonicalizableError",
    "canonical_bytes",
    "find_non_finite",
    "jcs_sha256",
    "prepare",
]

MAX_SAFE_INTEGER: Final = 2**53 - 1


class NotCanonicalizableError(ValueError):
    """Valor não finito no objeto (422 ``PACKAGE_NOT_CANONICALIZABLE``)."""

    def __init__(self, path: str) -> None:
        super().__init__(f"valor não finito em {path}")
        self.path = path


def find_non_finite(value: Any, path: str = "$") -> str | None:
    """Caminho JSON do primeiro ``float`` não finito, ou ``None``."""
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        item, where = stack.pop()
        if isinstance(item, float):
            if not math.isfinite(item):
                return where
        elif isinstance(item, dict):
            stack.extend((v, f"{where}.{k}") for k, v in reversed(list(item.items())))
        elif isinstance(item, list | tuple):
            stack.extend((v, f"{where}[{i}]") for i, v in reversed(list(enumerate(item))))
    return None


def prepare(value: Any) -> Any:
    """Cópia pronta para JCS: inteiros grandes em texto; ``NaN``/``inf`` recusados."""
    bad = find_non_finite(value)
    if bad is not None:
        raise NotCanonicalizableError(bad)
    return _prepare(value)


def _prepare(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, str | float):
        return value
    if isinstance(value, int):
        return str(value) if abs(value) > MAX_SAFE_INTEGER else value
    if isinstance(value, dict):
        return {str(k): _prepare(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_prepare(v) for v in value]
    raise TypeError(f"tipo não serializável em JSON: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    """Bytes JCS (RFC 8785) de ``value`` depois de ``prepare``."""
    try:
        return bytes(rfc8785.dumps(prepare(value)))
    except rfc8785.FloatDomainError as exc:  # defesa: prepare já recusa não finitos
        raise NotCanonicalizableError("$") from exc


def jcs_sha256(value: Any) -> str:
    """SHA-256 hex minúsculo dos bytes JCS de ``value``."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
